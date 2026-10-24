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
import math
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

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
        "news": lambda: stock.news,
    }
    for key, getter in parts.items():
        try:
            raw[key] = getter()
        except Exception as exc:  # one failing endpoint must not sink the rest
            raw[key] = None
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


def _published_from(content: dict, article: dict) -> Optional[str]:
    for key in ("pubDate", "displayTime"):
        value = content.get(key)
        if isinstance(value, str) and value:
            return value
    epoch = article.get("providerPublishTime")
    if isinstance(epoch, (int, float)):
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def parse_news(raw_news: Optional[Iterable], ticker: str, limit: int = 5) -> List[NewsItem]:
    """Turn Yahoo news items into NewsItem records.

    Handles both Yahoo formats: the current one (fields nested under
    "content") and the older flat one. Nothing is invented: a missing summary
    or link stays None and is shown as unavailable.
    """
    items: List[NewsItem] = []
    for article in raw_news or []:
        if not isinstance(article, dict):
            continue
        content = article.get("content") if isinstance(article.get("content"), dict) else {}
        headline = _clean_text(content.get("title") or article.get("title"))
        if not headline:
            continue
        summary = _clean_text(content.get("summary")) or _clean_text(content.get("description")) \
            or _clean_text(article.get("summary"))
        provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
        publisher = provider.get("displayName") or article.get("publisher")
        url = (
            _url_from(content.get("canonicalUrl"))
            or _url_from(content.get("clickThroughUrl"))
            or _url_from(article.get("link"))
        )
        items.append(
            NewsItem(
                ticker=ticker,
                headline=headline,
                summary=_shorten(summary),
                publisher=publisher if isinstance(publisher, str) and publisher else None,
                published_at=_published_from(content, article),
                source_url=url,
            )
        )
        if len(items) >= limit:
            break
    return items


def quote_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}"
