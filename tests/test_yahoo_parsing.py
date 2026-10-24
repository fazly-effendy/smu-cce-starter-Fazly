"""Parsing of Yahoo Finance data (no network: see fake_yahoo.py)."""

from __future__ import annotations

import pandas as pd
import pytest

import fake_yahoo
from services import yahoo


def test_unknown_ticker_raises_clear_error():
    with pytest.raises(yahoo.TickerNotFoundError, match="ZZZZ"):
        yahoo.fetch_price_history("ZZZZ", "1y")


def test_price_history_is_timezone_free_daily_closes():
    closes = yahoo.fetch_price_history("AAPL", "1y")
    assert closes.index.tz is None
    assert closes.iloc[0] == 200.0 and len(closes) == 30


def test_current_news_format_with_html_and_url_dictionaries():
    items = yahoo.parse_news(fake_yahoo.DATA["AAPL"]["news"], "AAPL")
    first, second = items
    assert first.headline == "Apple & partners expand $AAPL services"  # HTML entity decoded
    assert first.summary == "Apple announced an expansion of its services business."
    assert first.publisher == "Reuters"
    assert first.source_url == "https://finance.yahoo.com/news/apple-1.html"  # not a dict
    assert first.published_at == "2026-10-20T12:00:00Z"
    assert second.summary == "Market host discusses demand trends."  # HTML tags stripped
    assert second.source_url == "https://finance.yahoo.com/video/iphone.html"


def test_older_flat_news_format():
    (item,) = yahoo.parse_news(fake_yahoo.DATA["MSFT"]["news"], "MSFT")
    assert item.publisher == "Bloomberg"
    assert item.source_url == "https://example.com/msft-cloud"
    assert item.summary is None  # nothing invented when the source gives no summary
    assert item.published_at.endswith("Z")


def test_news_without_headline_is_skipped_and_limit_respected():
    raw = [{"content": {"title": ""}}] + [{"content": {"title": f"Story {i}"}} for i in range(10)]
    items = yahoo.parse_news(raw, "X", limit=5)
    assert [i.headline for i in items] == [f"Story {i}" for i in range(5)]
    assert all(i.source_url is None for i in items)


def test_statement_extraction_picks_named_rows_not_the_first_rows():
    items = yahoo.extract_statement_items(fake_yahoo.DATA["AAPL"]["income_stmt"], yahoo.INCOME_ITEMS)
    assert list(items) == ["Revenue", "Operating income", "Net income"]
    assert "Tax Effect Of Unusual Items" not in items
    assert items["Revenue"]["2025-09-30"] == 416e9


def test_statement_nan_becomes_none():
    table = pd.DataFrame({pd.Timestamp("2025-12-31"): [float("nan")]}, index=["Total Revenue"])
    assert yahoo.extract_statement_items(table, yahoo.INCOME_ITEMS) == {"Revenue": {"2025-12-31": None}}


def test_profile_and_ratings():
    profile = yahoo.extract_profile(fake_yahoo.DATA["MSFT"]["info"], "MSFT")
    assert profile["pe_ratio"] is None  # negative P/E is shown as N/A
    assert profile["market_cap"] == 3.1e12
    ratings = yahoo.extract_latest_ratings(fake_yahoo.DATA["AAPL"]["recommendations"])
    assert ratings["period"] == "0m" and ratings["buy"] == 21
    assert yahoo.extract_latest_ratings(pd.DataFrame()) is None
