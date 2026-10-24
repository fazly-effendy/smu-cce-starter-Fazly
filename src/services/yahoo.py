"""All Yahoo Finance access for Nimbus, via the yfinance package.

Built from the original notebooks (filings, news, stock_price_ratings) and the
earlier src/analysis.py. Functions here return plain Python data and never
touch Streamlit, so they can be tested and reused outside the app.

Two kinds of function:
- fetch_* call Yahoo and return raw data (the app caches these).
- parse_* / extract_* turn raw data into clean values and never call Yahoo.
"""

from __future__ import annotations

import html
import logging
import math
import re
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from models.briefing import NewsItem

SOURCE_NAME = "Yahoo Finance (via yfinance)"
_TAG_PATTERN = re.compile(r"<[^>]+>")

# Statement line items shown in the briefing: display name -> Yahoo row names
# to try in order (Yahoo's labels vary slightly between companies).
INCOME_ITEMS = {
    "Revenue": ["Total Revenue", "Operating Revenue"],
    "Operating income": ["Operating Income"],
    "Net income": ["Net Income", "Net Income Common Stockholders"],
}
BALANCE_ITEMS = {
    "Total assets": ["Total Assets"],
    "Total liabilities": ["Total Liabilities Net Minority Interest"],
    "Total debt": ["Total Debt"],
    "Shareholders' equity": ["Stockholders Equity", "Common Stock Equity"],
}
CASHFLOW_ITEMS = {
    "Operating cash flow": ["Operating Cash Flow"],
    "Free cash flow": ["Free Cash Flow"],
}


class TickerNotFoundError(ValueError):
    """Raised when Yahoo returns no price data for a ticker."""


# --------------------------------------------------------------------------
# Calls to Yahoo
# --------------------------------------------------------------------------

def fetch_price_history(ticker: str, period: str) -> pd.Series:
    """Daily adjusted closing prices for the period, indexed by date.

    Raises TickerNotFoundError when Yahoo has no prices (usually an unknown
    ticker).
    """
    history = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    if history is None or history.empty or "Close" not in history:
        raise TickerNotFoundError(f"No price data found for {ticker}. Check the ticker symbol.")
    closes = history["Close"].dropna()
    if closes.empty:
        raise TickerNotFoundError(f"No price data found for {ticker}. Check the ticker symbol.")
    index = pd.DatetimeIndex(closes.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    closes.index = index.normalize()
    closes = closes[~closes.index.duplicated(keep="last")]
    closes.name = ticker
    return closes.astype(float)


class _LogCapture(logging.Handler):
    """Collects warnings and errors that yfinance logs instead of raising."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: List[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def fetch_news(ticker: str, count: int = 10) -> dict:
    """Recent news for a ticker, with an honest account of what happened.

    yfinance's news feed returns an empty list (rather than an error) when Yahoo's
    news service answers unexpectedly, so this tries two routes:
    1. Ticker.get_news() - Yahoo's ticker news feed;
    2. Search(ticker).news - Yahoo's search service, a separate endpoint.
    Returns {"items": raw items, "source": which route worked, "status": "ok" |
    "empty" | "error", "message": explanation or None}.
    """
    logger = logging.getLogger("yfinance")
    capture = _LogCapture()
    logger.addHandler(capture)
    problems: List[str] = []
    try:
        try:
            items = yf.Ticker(ticker).get_news(count=count, tab="news") or []
        except Exception as exc:
            items = []
            problems.append(f"news feed failed ({exc.__class__.__name__}: {exc})")
        if items:
            return {"items": list(items), "source": "Yahoo Finance news", "status": "ok", "message": None}
        try:
            found = yf.Search(ticker, max_results=1, news_count=count).news or []
        except Exception as exc:
            found = []
            problems.append(f"news search failed ({exc.__class__.__name__}: {exc})")
        related = [a for a in found if isinstance(a, dict)
                   and ticker.upper() in [str(t).upper() for t in a.get("relatedTickers") or []]]
        found = related or found
        if found:
            return {"items": list(found), "source": "Yahoo Finance search", "status": "ok",
                    "message": "Yahoo's news feed returned nothing, so these articles come from Yahoo search."}
    finally:
        logger.removeHandler(capture)
    problems += [f"yfinance: {message}" for message in capture.messages[:3]]
    if problems:
        return {"items": [], "source": None, "status": "error", "message": "; ".join(problems)}
    return {"items": [], "source": None, "status": "empty",
            "message": "Yahoo returned no articles from either its news feed or its search service."}


def search_quotes(query: str, max_results: int = 8) -> List[dict]:
    """Yahoo Finance search results for a company name or ticker.

    Each result is a dict with keys such as symbol, longname, shortname,
    quoteType ("EQUITY", "ETF", ...), exchange (e.g. "NMS") and exchDisp
    (e.g. "NASDAQ"). Raises if Yahoo cannot be reached.
    """
    results = yf.Search(query, max_results=max_results, news_count=0).quotes
    return [dict(item) for item in results or [] if isinstance(item, dict)]


def fetch_company_data(ticker: str) -> dict:
    """Raw company data from Yahoo. Each part may independently be missing."""
    stock = yf.Ticker(ticker)
    raw: dict = {"warnings": []}
    parts = {
        "info": lambda: stock.info,
        "income_statement": lambda: stock.income_stmt,
        "balance_sheet": lambda: stock.balance_sheet,
        "cash_flow": lambda: stock.cashflow,
        "recommendations": lambda: stock.recommendations,
        "news": lambda: fetch_news(ticker),
        "calendar": lambda: stock.calendar,
        "earnings_dates": lambda: stock.get_earnings_dates(limit=8),
    }
    # Earnings data is often missing for non-US listings; its absence is shown as N/A, not as a warning.
    quiet = {"calendar", "earnings_dates"}
    for key, getter in parts.items():
        try:
            raw[key] = getter()
        except Exception as exc:  # one failing endpoint must not sink the rest
            raw[key] = None
            if key not in quiet:
                raw["warnings"].append(f"{key.replace('_', ' ').capitalize()} unavailable: {exc}")
    return raw


# --------------------------------------------------------------------------
# Parsing helpers (no network)
# --------------------------------------------------------------------------

def clean_number(value) -> Optional[float]:
    """Convert to float; missing, NaN, infinite or non-numeric values become None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def extract_profile(info: Optional[dict], ticker: str) -> dict:
    """Name, currency, market cap and P/E from Yahoo's info dictionary."""
    info = info or {}
    pe_ratio = clean_number(info.get("trailingPE"))
    return {
        "name": info.get("longName") or info.get("shortName") or ticker,
        "currency": info.get("currency"),
        "financial_currency": info.get("financialCurrency") or info.get("currency"),
        "market_cap": clean_number(info.get("marketCap")),
        # A negative or zero P/E is not meaningful; show N/A instead.
        "pe_ratio": pe_ratio if pe_ratio is not None and pe_ratio > 0 else None,
    }


def extract_statement_items(
    statement: Optional[pd.DataFrame], items: Dict[str, List[str]], max_years: int = 4
) -> Dict[str, Dict[str, Optional[float]]]:
    """Pick named line items from a yfinance statement (rows = items, columns = dates).

    Returns {display name: {YYYY-MM-DD: value or None}} for the most recent
    `max_years` fiscal years. Items Yahoo does not report are left out.
    """
    if statement is None or not isinstance(statement, pd.DataFrame) or statement.empty:
        return {}
    columns = sorted(statement.columns, reverse=True)[:max_years]
    result: Dict[str, Dict[str, Optional[float]]] = {}
    for display_name, row_names in items.items():
        row_name = next((name for name in row_names if name in statement.index), None)
        if row_name is None:
            continue
        row = statement.loc[row_name]
        if isinstance(row, pd.DataFrame):  # duplicated row label: keep the first
            row = row.iloc[0]
        result[display_name] = {
            pd.Timestamp(column).strftime("%Y-%m-%d"): clean_number(row.get(column))
            for column in columns
        }
    return result


def extract_latest_ratings(recommendations: Optional[pd.DataFrame]) -> Optional[dict]:
    """Analyst recommendation counts for the current month ("0m") if available."""
    if recommendations is None or not isinstance(recommendations, pd.DataFrame) or recommendations.empty:
        return None
    table = recommendations.reset_index(drop=True)
    if "period" in table.columns and (table["period"] == "0m").any():
        row = table[table["period"] == "0m"].iloc[0]
    else:
        row = table.iloc[-1]
    counts = {}
    for column in ("strongBuy", "buy", "hold", "sell", "strongSell"):
        value = clean_number(row.get(column))
        counts[column] = int(value) if value is not None else None
    if all(value is None for value in counts.values()):
        return None
    counts["period"] = str(row.get("period", "latest"))
    return counts


def _clean_text(value) -> Optional[str]:
    """Strip HTML tags and entities and collapse whitespace."""
    if not value or not isinstance(value, str):
        return None
    text = _TAG_PATTERN.sub(" ", value)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _shorten(text: Optional[str], limit: int = 320) -> Optional[str]:
    if text is None or len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def _url_from(value) -> Optional[str]:
    """Yahoo gives URLs either as strings or as {"url": ...} dictionaries."""
    if isinstance(value, dict):
        value = value.get("url")
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None


def _thumbnail_from(content: dict, article: dict) -> Optional[str]:
    """A small thumbnail URL if Yahoo provides one (prefers the 170x128 rendition)."""
    thumbnail = content.get("thumbnail") or article.get("thumbnail")
    if not isinstance(thumbnail, dict):
        return None
    resolutions = [r for r in thumbnail.get("resolutions") or [] if isinstance(r, dict) and _url_from(r.get("url"))]
    preferred = next((r for r in resolutions if r.get("tag") == "170x128"), None)
    if preferred is None and resolutions:
        preferred = min(resolutions, key=lambda r: r.get("width") or 10_000)
    return _url_from(preferred.get("url")) if preferred else _url_from(thumbnail.get("originalUrl"))


def _published_from(content: dict, article: dict) -> Optional[str]:
    for key in ("pubDate", "displayTime"):
        value = content.get(key)
        if isinstance(value, str) and value:
            return value
    epoch = article.get("providerPublishTime")
    if isinstance(epoch, (int, float)):
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _parse_article(article, ticker: str) -> Optional[NewsItem]:
    """One Yahoo news item -> NewsItem, or None if it has no headline."""
    if not isinstance(article, dict):
        return None
    content = article.get("content") if isinstance(article.get("content"), dict) else {}
    headline = _clean_text(content.get("title") or article.get("title"))
    if not headline:
        return None
    summary = _clean_text(content.get("summary")) or _clean_text(content.get("description")) \
        or _clean_text(article.get("summary"))
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    publisher = provider.get("displayName") or article.get("publisher")
    url = (
        _url_from(content.get("canonicalUrl"))
        or _url_from(content.get("clickThroughUrl"))
        or _url_from(article.get("link"))
    )
    return NewsItem(
        ticker=ticker,
        headline=headline,
        summary=_shorten(summary),
        publisher=publisher if isinstance(publisher, str) and publisher else None,
        published_at=_published_from(content, article),
        source_url=url,
        thumbnail_url=_thumbnail_from(content, article),
    )


def parse_news_with_count(raw_news: Optional[Iterable], ticker: str, limit: int = 5) -> Tuple[List[NewsItem], int]:
    """Parse Yahoo news items in either format. Returns (items, number of malformed items skipped).

    Formats: the current one nests fields under "content" (title, summary, pubDate,
    provider.displayName, canonicalUrl.url, thumbnail.resolutions); the older/search
    one is flat (title, publisher, link, providerPublishTime, thumbnail). One broken
    item is skipped and counted; it never stops the others.
    """
    items: List[NewsItem] = []
    skipped = 0
    for article in raw_news or []:
        try:
            item = _parse_article(article, ticker)
        except Exception:
            item = None
        if item is None:
            skipped += 1
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items, skipped


def parse_news(raw_news: Optional[Iterable], ticker: str, limit: int = 5) -> List[NewsItem]:
    """Turn Yahoo news items into NewsItem records. Nothing is invented: a missing
    summary or link stays None and is shown as unavailable."""
    return parse_news_with_count(raw_news, ticker, limit)[0]


def quote_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}"


# --------------------------------------------------------------------------
# Analyst consensus and earnings (no network)
# --------------------------------------------------------------------------

def extract_analyst_view(info: Optional[dict], last_close: Optional[float]) -> Optional[dict]:
    """Consensus recommendation and price targets from Yahoo's info dictionary.

    Upside = mean price target / last close - 1 (both in the trading currency).
    """
    info = info or {}
    target = clean_number(info.get("targetMeanPrice"))
    analysts = clean_number(info.get("numberOfAnalystOpinions"))
    key = info.get("recommendationKey")
    recommendation = key.replace("_", " ") if isinstance(key, str) and key and key != "none" else None
    view = {
        "recommendation": recommendation,
        "recommendation_mean": clean_number(info.get("recommendationMean")),  # 1 = strong buy ... 5 = sell
        "analysts": int(analysts) if analysts else None,
        "target_mean": target,
        "target_high": clean_number(info.get("targetHighPrice")),
        "target_low": clean_number(info.get("targetLowPrice")),
        "upside": (target / last_close - 1.0) if target and last_close and last_close > 0 else None,
    }
    return view if any(value is not None for value in view.values()) else None


def _to_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError):
        return None


def extract_earnings(calendar, earnings_dates, today: date) -> Optional[dict]:
    """Next earnings date and EPS estimate, and how the last reported EPS compared with its estimate.

    Surprise = (reported EPS - estimate) / |estimate|, computed here rather than taken from Yahoo.
    """
    result: Dict[str, object] = {
        "next_date": None, "next_eps_estimate": None, "last_date": None,
        "last_eps_estimate": None, "last_eps_actual": None, "last_surprise": None, "last_result": None,
    }
    if isinstance(calendar, dict):
        dates = calendar.get("Earnings Date") or []
        if not isinstance(dates, (list, tuple)):
            dates = [dates]
        upcoming = sorted(d for d in (_to_date(x) for x in dates) if d and d >= today)
        if upcoming:
            result["next_date"] = upcoming[0].isoformat()
            result["next_eps_estimate"] = clean_number(calendar.get("Earnings Average"))

    if isinstance(earnings_dates, pd.DataFrame) and not earnings_dates.empty:
        table = earnings_dates.copy()
        table["_date"] = [_to_date(index) for index in table.index]
        if "Reported EPS" in table.columns:
            reported = table[table["Reported EPS"].notna()].sort_values("_date", ascending=False)
            if not reported.empty:
                row = reported.iloc[0]
                actual = clean_number(row.get("Reported EPS"))
                estimate = clean_number(row.get("EPS Estimate"))
                result["last_date"] = row["_date"].isoformat() if row["_date"] else None
                result["last_eps_actual"] = actual
                result["last_eps_estimate"] = estimate
                if actual is not None and estimate is not None:
                    result["last_result"] = "beat" if actual > estimate else "miss" if actual < estimate else "in line"
                    if estimate != 0:
                        result["last_surprise"] = (actual - estimate) / abs(estimate)
            if result["next_date"] is None:
                future = table[table["Reported EPS"].isna() & table["_date"].map(lambda d: d is not None and d >= today)]
                if not future.empty:
                    row = future.sort_values("_date").iloc[0]
                    result["next_date"] = row["_date"].isoformat()
                    result["next_eps_estimate"] = clean_number(row.get("EPS Estimate"))
    return result if any(value is not None for value in result.values()) else None
