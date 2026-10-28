"""News summaries from Yahoo's RSS headline feed (Feature 1: "news needs a summary and a source").

Yahoo's news feed currently returns nothing and Yahoo search articles carry no summary (checked live
on 29 Oct 2026 with scripts/debug_news.py). Yahoo's RSS feed has a description for each article but
no publisher. Nimbus combines them without generating any text.
"""

from __future__ import annotations

import fake_yahoo
from services import yahoo
from services.briefing_builder import build_briefing
from storage import briefing_store, snapshots
from test_storage import make_note

RSS_DATE = "Wed, 28 Oct 2026 18:00:00 +0000"


def rss(*items):
    return fake_yahoo.rss_xml(*items)


def test_rss_feed_is_read_into_the_search_format():
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(("Apple unveils a touchscreen MacBook", "https://example.com/mac",
                                        "Apple&#39;s first touchscreen <b>laptop</b>.", RSS_DATE))
    [item] = yahoo.fetch_rss("AAPL")
    assert item["title"] == "Apple unveils a touchscreen MacBook"
    assert item["providerPublishTime"] == 1793210400  # 28 Oct 2026 18:00 UTC
    assert item["publisher"] is None and item["nimbus_via"] == "Yahoo Finance RSS"
    parsed = yahoo.parse_news([item], "AAPL")[0]
    assert parsed.summary == "Apple's first touchscreen laptop."  # HTML removed, nothing added
    assert parsed.via == "Yahoo Finance RSS" and parsed.publisher is None


def test_search_article_gets_the_rss_summary_and_keeps_its_publisher():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    # Same article, written slightly differently in the two feeds (case, spacing, punctuation).
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(("APPLE supplier outlook improves!", "https://other.example/x",
                                        "Suppliers expect stronger iPhone orders.", RSS_DATE))
    result = yahoo.fetch_news("AAPL", name="Apple Inc.")
    [item] = yahoo.parse_news(result["items"], "AAPL")
    assert item.headline == "Apple supplier outlook improves"
    assert item.publisher == "Barron's"  # from Yahoo search
    assert item.summary == "Suppliers expect stronger iPhone orders."
    assert item.summary_source == "Yahoo Finance RSS"
    assert result["source"] == "Yahoo Finance search + RSS"


def test_articles_are_matched_by_link_when_headlines_differ():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(("A different headline", "https://example.com/apple-suppliers",
                                        "Matched by link.", RSS_DATE))
    items = yahoo.parse_news(yahoo.fetch_news("AAPL", name="Apple Inc.")["items"], "AAPL")
    assert [(i.headline, i.summary) for i in items] == [("Apple supplier outlook improves", "Matched by link.")]


def test_rss_only_articles_need_the_company_in_the_headline():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(
        ("Apple is at a record going into earnings", "https://example.com/a1", "Shares are up.", RSS_DATE),
        ("Intel fell 24% in a month", "https://example.com/a2", "Rivals Apple and AMD gained.", RSS_DATE),
        ("Is job hopping still benefiting workers?", "https://example.com/a3", "A panel discusses.", RSS_DATE),
    )
    items = yahoo.parse_news(yahoo.fetch_news("AAPL", name="Apple Inc.")["items"], "AAPL", limit=10)
    headlines = [i.headline for i in items]
    assert "Apple is at a record going into earnings" in headlines
    assert "Intel fell 24% in a month" not in headlines  # names Apple only in the summary
    assert "Is job hopping still benefiting workers?" not in headlines
    rss_only = next(i for i in items if i.headline.startswith("Apple is at a record"))
    assert rss_only.publisher is None and rss_only.via == "Yahoo Finance RSS"
    assert rss_only.summary == "Shares are up." and rss_only.summary_source is None


def test_listing_with_no_search_news_gets_rss_articles():
    """Live check on 29 Oct 2026: Yahoo search returned no news for D05.SI; the RSS feed had 10 relevant."""
    fake_yahoo.NEWS_FEED_MODE = "empty"
    fake_yahoo.RSS_FEEDS["D05.SI"] = rss(
        ("DBS CEO: market repricing risks on AI financing", "https://example.com/d1", "Tan Su Shan says…", RSS_DATE),
        ("Citigroup completed a weekend tokenized-dollar transfer", "https://example.com/d2", "DBS took part.", RSS_DATE),
    )
    result = yahoo.fetch_news("D05.SI", name="DBS Group Holdings Ltd")
    assert result["status"] == "ok" and result["source"] == "Yahoo Finance RSS"
    assert [i.headline for i in yahoo.parse_news(result["items"], "D05.SI")] == [
        "DBS CEO: market repricing risks on AI financing"]


def test_rss_failure_leaves_search_results_unchanged():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    fake_yahoo.RSS_ONLINE = False
    result = yahoo.fetch_news("AAPL", name="Apple Inc.")
    [item] = yahoo.parse_news(result["items"], "AAPL")
    assert item.headline == "Apple supplier outlook improves" and item.summary is None
    assert result["source"] == "Yahoo Finance search"
    assert "RSS feed failed (ConnectionError)" in result["message"]


def test_rss_is_not_used_when_the_main_news_feed_works():
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(("Apple is at a record", "https://example.com/a1", "Up.", RSS_DATE))
    result = yahoo.fetch_news("AAPL", name="Apple Inc.")
    assert result["source"] == "Yahoo Finance news"
    assert fake_yahoo.CALLS[("rss", "AAPL")] == 0


def test_combined_news_is_newest_first_and_limited_per_company():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(*[
        (f"Apple story {n}", f"https://example.com/s{n}", f"Summary {n}.", f"Wed, 28 Oct 2026 1{n}:00:00 +0000")
        for n in range(8)
    ])
    briefing = build_briefing(["AAPL", "MSFT"], "1 year", "1y", yahoo.fetch_price_history, yahoo.fetch_company_data)
    news = briefing.companies[0].news
    assert len(news) == 5
    assert [n.headline for n in news] == [f"Apple story {n}" for n in (7, 6, 5, 4, 3)]  # newest first


def test_summaries_and_their_source_are_kept_in_the_saved_snapshot(isolated_environment):
    fake_yahoo.NEWS_FEED_MODE = "empty"
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(
        ("Apple supplier outlook improves", "https://example.com/apple-suppliers", "Stronger orders.", RSS_DATE),
        ("Apple is at a record", "https://example.com/a1", "Shares are up.", RSS_DATE),
    )
    briefing = build_briefing(["AAPL", "MSFT"], "1 year", "1y", yahoo.fetch_price_history, yahoo.fetch_company_data)
    result = briefing_store.save_discussion(briefing, make_note())
    reopened, _ = briefing_store.open_discussion(briefing.briefing_id)
    assert reopened.companies[0].news == briefing.companies[0].news
    text = (isolated_environment / result.filename).read_text()
    assert "Stronger orders. (summary via Yahoo Finance RSS)" in text
    assert "via Yahoo Finance RSS (publisher not listed)" in text
    assert snapshots.briefing_markdown(reopened).count("summary via Yahoo Finance RSS") == 1


def test_news_tab_labels_rss_summaries_and_sources():
    from test_app_workflow import generate, start_app

    fake_yahoo.NEWS_FEED_MODE = "empty"
    fake_yahoo.RSS_FEEDS["AAPL"] = rss(
        ("Apple supplier outlook improves", "https://example.com/apple-suppliers", "Stronger orders.", RSS_DATE),
        ("Apple is at a record", "https://example.com/a1", "Shares are up.", RSS_DATE),
    )
    app = generate(start_app(), "AAPL, MSFT")
    page = " ".join(m.value for m in app.markdown)
    assert "Stronger orders. _(summary via Yahoo Finance RSS)_" in page
    assert "Barron&#x27;s" in page or "Barron's" in page  # the search article keeps its publisher
    assert "via Yahoo Finance RSS (publisher not listed)" in page
    status = next(c.value for c in app.caption if c.value.startswith("For this comparison: "))
    assert "AAPL: Yahoo's news feed was empty, so articles come from Yahoo search, with summaries" in status
