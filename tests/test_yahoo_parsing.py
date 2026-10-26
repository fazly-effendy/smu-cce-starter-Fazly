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


def test_news_thumbnail_prefers_small_rendition():
    items = yahoo.parse_news(fake_yahoo.DATA["AAPL"]["news"], "AAPL")
    assert items[0].thumbnail_url == "https://s.yimg.com/apple-170.jpg"
    assert items[1].thumbnail_url is None


def test_analyst_view_and_upside():
    view = yahoo.extract_analyst_view(fake_yahoo.DATA["AAPL"]["info"], 229.0)
    assert view["recommendation"] == "buy" and view["analysts"] == 40
    assert view["upside"] == pytest.approx(251.9 / 229.0 - 1)
    assert yahoo.extract_analyst_view({"recommendationKey": "none"}, 100.0) is None
    assert yahoo.extract_analyst_view({"targetMeanPrice": 50.0}, None)["upside"] is None


def test_earnings_next_date_and_last_result():
    from datetime import timedelta
    data = fake_yahoo.DATA["MSFT"]
    today = fake_yahoo.NEXT_EARNINGS - timedelta(days=5)
    earnings = yahoo.extract_earnings(data["calendar"], data["earnings_dates"], today)
    assert earnings["next_date"] == fake_yahoo.NEXT_EARNINGS.isoformat()
    assert earnings["next_eps_estimate"] == 3.62
    assert earnings["last_date"] == fake_yahoo.LAST_EARNINGS.isoformat()
    assert earnings["last_result"] == "beat"
    assert earnings["last_surprise"] == pytest.approx((3.65 - 3.35) / 3.35)


def test_earnings_after_the_scheduled_date_and_when_missing():
    from datetime import timedelta
    data = fake_yahoo.DATA["MSFT"]
    later = fake_yahoo.NEXT_EARNINGS + timedelta(days=1)
    assert yahoo.extract_earnings(data["calendar"], data["earnings_dates"], later)["next_date"] is None
    assert yahoo.extract_earnings(None, None, later) is None
    missed = pd.DataFrame({"EPS Estimate": [2.0], "Reported EPS": [1.5]},
                          index=pd.DatetimeIndex(["2026-01-01"], name="Earnings Date"))
    result = yahoo.extract_earnings({}, missed, later)
    assert result["last_result"] == "miss" and result["last_surprise"] == pytest.approx(-0.25)


def test_fetch_news_uses_main_feed_when_it_works():
    result = yahoo.fetch_news("AAPL")
    assert result["status"] == "ok" and result["source"] == "Yahoo Finance news" and len(result["items"]) == 2


def test_fetch_news_falls_back_to_search_when_feed_is_empty():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    result = yahoo.fetch_news("AAPL")
    assert result["source"] == "Yahoo Finance search"
    assert [a["uuid"] for a in result["items"]] == ["s1"]  # only articles tagged with AAPL
    items, skipped = yahoo.parse_news_with_count(result["items"], "AAPL")
    assert items[0].headline == "Apple supplier outlook improves" and items[0].publisher == "Barron's"
    assert items[0].thumbnail_url == "https://s.yimg.com/s1-140.jpg" and skipped == 0


def test_fetch_news_reports_real_errors_instead_of_no_news():
    fake_yahoo.NEWS_FEED_MODE = "error"
    fake_yahoo.SEARCH_ONLINE = False
    result = yahoo.fetch_news("AAPL")
    assert result["status"] == "error"
    assert "news feed failed (ConnectionError: news feed unreachable)" in result["message"]
    assert "news search failed" in result["message"]


def test_fetch_news_genuinely_empty():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    result = yahoo.fetch_news("MSFT")  # search has no news for MSFT either
    assert result["status"] == "empty" and "no articles" in result["message"]


def test_malformed_news_items_are_skipped_and_counted():
    raw = [{"content": {"title": "Good one"}}, {"content": "not a dict"}, None, 42, {"content": {"title": ""}},
           {"title": "Flat good one", "link": "https://example.com/x"}]
    items, skipped = yahoo.parse_news_with_count(raw, "X", limit=10)
    assert [i.headline for i in items] == ["Good one", "Flat good one"] and skipped == 4
