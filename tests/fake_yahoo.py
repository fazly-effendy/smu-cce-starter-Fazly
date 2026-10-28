"""A stand-in for the yfinance package so tests run without internet access.

The data imitates the shapes yfinance returns today: tz-aware price history,
statement tables with dates as columns, the nested news format (with HTML in
"description" and URLs as {"url": ...} dictionaries), and the older flat news
format. Every call is counted so tests can prove that reopening a saved
briefing makes no Yahoo calls.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pandas as pd

CALLS: Counter = Counter()

NEXT_EARNINGS = date.today() + timedelta(days=5)
LAST_EARNINGS = date.today() - timedelta(days=86)

FY = [pd.Timestamp("2025-09-30"), pd.Timestamp("2024-09-30"), pd.Timestamp("2023-09-30")]


def _statement(rows: dict, dates=FY) -> pd.DataFrame:
    return pd.DataFrame({d: [values[i] for values in rows.values()] for i, d in enumerate(dates)}, index=list(rows))


def _history(start_price: float, step: float, skip=None) -> pd.DataFrame:
    dates = pd.bdate_range("2026-09-01", periods=30, tz="America/New_York")
    if skip is not None:
        dates = dates.delete(skip)
    prices = [start_price + step * i for i in range(len(dates))]
    return pd.DataFrame({"Open": prices, "Close": prices, "Volume": 1000}, index=dates)


DATA = {
    "AAPL": {
        "history": _history(200.0, 1.0),
        "info": {"longName": "Apple Inc.", "currency": "USD", "financialCurrency": "USD",
                 "marketCap": 3.5e12, "trailingPE": 33.456, "recommendationKey": "buy",
                 "recommendationMean": 1.9, "numberOfAnalystOpinions": 40, "targetMeanPrice": 251.9,
                 "targetHighPrice": 300.0, "targetLowPrice": 180.0},
        "income_stmt": _statement({
            "Tax Effect Of Unusual Items": [1.0, 2.0, 3.0],
            "Total Revenue": [416e9, 391e9, 383e9],
            "Operating Income": [133e9, 123e9, 114e9],
            "Net Income": [112e9, 94e9, 97e9],
        }),
        "balance_sheet": _statement({
            "Total Assets": [360e9, 365e9, 352e9],
            "Total Liabilities Net Minority Interest": [290e9, 308e9, 290e9],
            "Total Debt": [100e9, 107e9, 111e9],
            "Stockholders Equity": [70e9, 57e9, 62e9],
        }),
        "cashflow": _statement({"Operating Cash Flow": [110e9, 118e9, 110e9], "Free Cash Flow": [99e9, 108e9, 99e9]}),
        "recommendations": pd.DataFrame({"period": ["0m", "-1m"], "strongBuy": [7, 8], "buy": [21, 20],
                                         "hold": [14, 13], "sell": [2, 1], "strongSell": [1, 1]}),
        "news": [
            {"id": "a1", "content": {
                "title": "Apple &amp; partners expand $AAPL services",
                "summary": "Apple announced an expansion of its services business.",
                "description": "<p>Ignored because summary exists</p>",
                "pubDate": "2026-10-20T12:00:00Z",
                "provider": {"displayName": "Reuters", "url": "https://www.reuters.com"},
                "canonicalUrl": {"url": "https://finance.yahoo.com/news/apple-1.html", "site": "finance"},
                "thumbnail": {"originalUrl": "https://s.yimg.com/apple-original.jpg", "resolutions": [
                    {"url": "https://s.yimg.com/apple-original.jpg", "width": 1200, "height": 800, "tag": "original"},
                    {"url": "https://s.yimg.com/apple-170.jpg", "width": 170, "height": 128, "tag": "170x128"},
                ]},
            }},
            {"id": "a2", "content": {
                "title": "Analysts review iPhone demand",
                "summary": "",
                "description": "<p>Market host discusses <a href=\"x\">demand</a> trends.</p>",
                "pubDate": "2026-10-19T08:30:00Z",
                "provider": {"displayName": "Yahoo Finance Video"},
                "canonicalUrl": None,
                "clickThroughUrl": {"url": "https://finance.yahoo.com/video/iphone.html"},
            }},
        ],
    },
    "MSFT": {
        "history": _history(400.0, -1.0, skip=5),  # one missing day: tests date alignment
        "info": {"longName": "Microsoft Corporation", "currency": "USD", "financialCurrency": "USD",
                 "marketCap": 3.1e12, "trailingPE": -5.0},  # negative P/E must show N/A
        "income_stmt": _statement({
            "Total Revenue": [282e9, 245e9, 212e9],
            "Net Income": [101e9, 88e9, 72e9],
        }, dates=[pd.Timestamp("2025-06-30"), pd.Timestamp("2024-06-30"), pd.Timestamp("2023-06-30")]),
        "balance_sheet": _statement({
            "Total Assets": [619e9, 512e9, 412e9],
            "Stockholders Equity": [343e9, 268e9, 206e9],
        }, dates=[pd.Timestamp("2025-06-30"), pd.Timestamp("2024-06-30"), pd.Timestamp("2023-06-30")]),
        "cashflow": pd.DataFrame(),
        "recommendations": pd.DataFrame(),
        # Dates relative to today so the "next earnings" stays in the future whenever tests run.
        "calendar": {"Earnings Date": [NEXT_EARNINGS], "Earnings Average": 3.62, "Earnings Low": 3.4,
                     "Earnings High": 3.8, "Revenue Average": 7.5e10},
        "earnings_dates": pd.DataFrame(
            {"EPS Estimate": [3.62, 3.35, 3.22], "Reported EPS": [float("nan"), 3.65, 3.10],
             "Surprise(%)": [float("nan"), 8.96, -3.73]},
            index=pd.DatetimeIndex([pd.Timestamp(NEXT_EARNINGS), pd.Timestamp(LAST_EARNINGS),
                                    pd.Timestamp(LAST_EARNINGS - timedelta(days=91))],
                                   name="Earnings Date").tz_localize("America/New_York")),
        "news": [
            {"title": "Microsoft cloud revenue rises", "publisher": "Bloomberg",
             "link": "https://example.com/msft-cloud", "providerPublishTime": 1792500000},
        ],
    },
}


class FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._data = DATA.get(symbol)

    def _get(self, key, empty):
        CALLS[(self.symbol, key)] += 1
        return self._data[key] if self._data else empty

    def history(self, period="1y", auto_adjust=True):
        return self._get("history", pd.DataFrame())

    @property
    def info(self):
        return self._get("info", {"trailingPegRatio": None})

    @property
    def income_stmt(self):
        return self._get("income_stmt", pd.DataFrame())

    @property
    def balance_sheet(self):
        return self._get("balance_sheet", pd.DataFrame())

    @property
    def cashflow(self):
        return self._get("cashflow", pd.DataFrame())

    @property
    def recommendations(self):
        return self._get("recommendations", pd.DataFrame())

    @property
    def news(self):
        return self._get("news", [])

    def get_news(self, count=10, tab="news"):
        if NEWS_FEED_MODE == "empty":
            return []
        if NEWS_FEED_MODE == "error":
            raise ConnectionError("news feed unreachable")
        return self.news[:count]

    @property
    def calendar(self):
        return self._get("calendar", {}) if self._data and "calendar" in self._data else {}

    def get_earnings_dates(self, limit=12):
        return self._get("earnings_dates", None) if self._data and "earnings_dates" in self._data else None


# Search results shaped like yfinance Search(...).quotes. Keys are lower-case queries.
SEARCH_RESULTS = {
    "palantir": [
        {"symbol": "PTX.F", "longname": "Palantir Technologies Inc.", "quoteType": "EQUITY", "exchange": "FRA",
         "exchDisp": "Frankfurt"},
        {"symbol": "PLTR", "longname": "Palantir Technologies Inc.", "quoteType": "EQUITY", "exchange": "NMS",
         "exchDisp": "NASDAQ"},
        {"symbol": "PLTX", "shortname": "Palantir 2x ETF", "quoteType": "ETF", "exchange": "NMS",
         "exchDisp": "NASDAQ"},
    ],
    "nvid": [
        {"symbol": "NVDA", "longname": "NVIDIA Corporation", "quoteType": "EQUITY", "exchange": "NMS",
         "exchDisp": "NASDAQ"},
        {"symbol": "NVD.DE", "longname": "NVIDIA Corporation", "quoteType": "EQUITY", "exchange": "GER",
         "exchDisp": "XETRA"},
    ],
    "meta": [
        {"symbol": "META", "longname": "Meta Platforms, Inc.", "quoteType": "EQUITY", "exchange": "NMS",
         "exchDisp": "NASDAQ"},
        {"symbol": "MMAT", "longname": "Meta Materials Inc.", "quoteType": "EQUITY", "exchange": "PNK",
         "exchDisp": "OTC Markets"},
    ],
    "aapl": [
        {"symbol": "AAPL", "longname": "Apple Inc.", "quoteType": "EQUITY", "exchange": "NMS", "exchDisp": "NASDAQ"},
    ],
    "dbs group": [
        {"symbol": "DBSDY", "longname": "DBS Group Holdings Ltd", "quoteType": "EQUITY", "exchange": "PNK",
         "exchDisp": "OTC Markets"},
        {"symbol": "D05.SI", "longname": "DBS Group Holdings Ltd", "quoteType": "EQUITY", "exchange": "SES",
         "exchDisp": "Singapore"},
    ],
}
SEARCH_ONLINE = True  # set to False in a test to simulate Yahoo being unreachable
NEWS_FEED_MODE = "ok"  # "empty" or "error" simulates Yahoo's news feed failing (search still works)

# News from Yahoo's search service (the older flat format), keyed by lower-case query.
SEARCH_NEWS = {
    "aapl": [
        {"uuid": "s1", "title": "Apple supplier outlook improves", "publisher": "Barron's",
         "link": "https://example.com/apple-suppliers", "providerPublishTime": 1792000000, "type": "STORY",
         "relatedTickers": ["AAPL", "TSM"],
         "thumbnail": {"resolutions": [{"url": "https://s.yimg.com/s1-140.jpg", "width": 140, "height": 140,
                                         "tag": "140x140"}]}},
        {"uuid": "s2", "title": "Unrelated market wrap", "publisher": "Reuters",
         "link": "https://example.com/wrap", "providerPublishTime": 1791990000, "relatedTickers": ["SPY"]},
        {"uuid": "bad"},  # malformed: no title
    ],
}


# Yahoo's RSS headline feed, keyed by ticker. Unknown tickers get an empty feed.
RSS_FEEDS: dict = {}
RSS_ONLINE = True  # set to False in a test to simulate the RSS feed being unreachable


def rss_xml(*items) -> bytes:
    """Build an RSS document from (title, link, description, pubDate) tuples."""
    from xml.sax.saxutils import escape

    body = "".join(
        f"<item><title>{escape(t)}</title><link>{escape(l)}</link><description>{escape(d)}</description>"
        f"<pubDate>{p}</pubDate><guid>{escape(l)}</guid></item>"
        for t, l, d, p in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Yahoo</title>{body}</channel></rss>'.encode()


class FakeRssResponse:
    def __init__(self, content: bytes, status: int = 200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def fake_rss_get(ticker: str):
    CALLS[("rss", ticker)] += 1
    if not RSS_ONLINE:
        raise ConnectionError("RSS feed unreachable")
    return FakeRssResponse(RSS_FEEDS.get(ticker.upper(), rss_xml()))


class FakeSearch:
    def __init__(self, query, max_results=8, news_count=8, **kwargs):
        CALLS[("search", query)] += 1
        if not SEARCH_ONLINE:
            raise ConnectionError("Yahoo search unreachable")
        self.quotes = SEARCH_RESULTS.get(query.strip().lower(), [])[:max_results]
        self.news = SEARCH_NEWS.get(query.strip().lower(), [])[:news_count]


class FakeYF:
    Ticker = FakeTicker
    Search = FakeSearch


def total_calls() -> int:
    return sum(CALLS.values())


def data_calls() -> int:
    """Calls that retrieve market data (searches excluded)."""
    return sum(count for key, count in CALLS.items() if key[0] != "search")
