"""Regression tests for defects found in the QA run on the AWS deployment (25 Oct 2026, AWS-QA-20261024T181839Z).

The tab-reset defect (typed notes lost on Streamlit 1.50) is covered by
test_tabs_keep_their_place_between_runs in test_app_workflow.py.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from streamlit.testing.v1 import AppTest

import fake_yahoo
from analytics.formatting import format_timestamp
from services import yahoo
from services.briefing_builder import build_briefing
from storage import briefing_store, database, snapshots
from test_app_workflow import APP, button
from test_storage import make_briefing, make_note


# --- Dates and times follow the RM's time zone (Singapore by default) -------------------------

def test_times_are_shown_in_singapore_time(monkeypatch):
    monkeypatch.setenv("NIMBUS_TIMEZONE", "Asia/Singapore")
    assert format_timestamp("2026-10-24T18:21:00Z") == "25 Oct 2026, 02:21 SGT"


def test_unknown_time_zone_falls_back_to_utc(monkeypatch):
    monkeypatch.setenv("NIMBUS_TIMEZONE", "Not/A_Zone")
    assert format_timestamp("2026-10-24T18:21:00Z") == "24 Oct 2026, 18:21 UTC"


def test_date_search_uses_the_local_date(monkeypatch):
    """QA: saved at 02:21 on 25 Oct in Singapore (18:21 UTC on 24 Oct); searching 25 Oct found nothing.
    Without an explicit discussion date, the local date of saving is used."""
    from dataclasses import replace

    monkeypatch.setenv("NIMBUS_TIMEZONE", "Asia/Singapore")
    briefing = replace(make_briefing(), saved_at="2026-10-24T18:21:53Z",
                       note=make_note(discussion_date=None))
    database.insert_discussion(briefing, "case-01.md")

    found = database.search_discussions(date_from=date(2026, 10, 25), date_to=date(2026, 10, 25))
    assert [row["discussion_id"] for row in found] == [briefing.briefing_id]
    assert database.search_discussions(date_from=date(2026, 10, 24), date_to=date(2026, 10, 24)) == []


# --- News: only articles Yahoo links to the company ------------------------------------------

def test_search_fallback_hides_articles_not_linked_to_the_ticker(monkeypatch):
    """QA: Netflix, Nike and Bloom Energy stories were tagged as NVDA news."""
    fake_yahoo.NEWS_FEED_MODE = "empty"
    monkeypatch.setitem(fake_yahoo.SEARCH_NEWS, "nvda", [
        {"uuid": "n1", "title": "Netflix subscriber growth", "publisher": "Reuters",
         "link": "https://example.com/nflx", "providerPublishTime": 1792000000, "relatedTickers": ["NFLX"]},
        {"uuid": "n2", "title": "Nike earnings preview", "publisher": "Barron's",
         "link": "https://example.com/nke", "providerPublishTime": 1792000000},
    ])
    result = yahoo.fetch_news("NVDA")
    assert result["items"] == []
    assert result["status"] == "empty"
    assert "none linked to NVDA" in result["message"]


def test_search_fallback_keeps_linked_articles():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    result = yahoo.fetch_news("AAPL")
    assert [item["uuid"] for item in result["items"]] == ["s1"]  # the unrelated market wrap is dropped
    assert result["source"] == "Yahoo Finance search"


# --- Missing data is shown, not dropped ---------------------------------------------------------

def test_missing_statement_item_is_shown_as_not_available():
    """QA: NVDA's Total liabilities row disappeared instead of showing N/A."""
    briefing = make_briefing()
    briefing.companies[0].financials.pop("Total liabilities", None)
    markdown = snapshots.briefing_markdown(briefing)
    row = next(line for line in markdown.splitlines() if line.startswith("| Total liabilities"))
    assert "N/A" in row


# --- Retrieval time is when Yahoo was actually called ------------------------------------------

def test_retrieval_time_comes_from_the_fetch_not_the_briefing():
    """QA: a briefing said 'retrieved 18:28' although its data was reused from an 18:18 fetch."""
    def fetch_company(ticker):
        raw = yahoo.fetch_company_data(ticker)
        raw["retrieved_at"] = "2026-10-24T18:18:00Z"  # as if cached 10 minutes earlier
        return raw

    briefing = build_briefing(["AAPL", "MSFT"], "1 year", "1y", yahoo.fetch_price_history, fetch_company)
    assert [c.retrieved_at for c in briefing.companies] == ["2026-10-24T18:18:00Z"] * 2
    assert briefing.created_at != "2026-10-24T18:18:00Z"


# --- History tab ----------------------------------------------------------------------------------

def test_from_date_after_to_date_is_rejected():
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    date_inputs = [d for d in app.date_input if d.label.startswith("Discussion")]
    date_inputs[0].set_value(date(2026, 10, 26))
    date_inputs[1].set_value(date(2026, 10, 25))
    button(app, "Search").click().run()
    assert not app.exception, app.exception
    assert any("after “Discussion to”" in e.value for e in app.error)


def test_selector_shows_the_briefing_opened_from_the_sidebar():
    """QA: 'Choose a saved briefing' could show a different record from the one open on screen."""
    older = make_briefing(("AAPL", "MSFT"))
    briefing_store.save_discussion(older, make_note("C-1001", discussion_date="2026-10-20"))
    newer = make_briefing(("MSFT",))
    briefing_store.save_discussion(newer, make_note("C-2002", discussion_date="2026-10-24"))

    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    sidebar_button = next(b for b in app.sidebar.button if b.key == f"recent_{older.briefing_id}")
    sidebar_button.click().run()
    assert not app.exception, app.exception

    chooser = next(s for s in app.selectbox if s.label == "Choose a saved discussion")
    assert chooser.value == older.briefing_id
    assert app.session_state["open_briefing_id"] == older.briefing_id


# --- Second AWS QA run (27 Oct 2026, AUDIT-RUN-20261026-01) -------------------------------------

def test_search_fallback_drops_linked_articles_that_do_not_name_the_company(monkeypatch):
    """QA round 2: Yahoo linked 'Why PagSeguro Stock Crashed Today' to NVDA."""
    fake_yahoo.NEWS_FEED_MODE = "empty"
    monkeypatch.setitem(fake_yahoo.SEARCH_NEWS, "nvda", [
        {"uuid": "p1", "title": "Why PagSeguro Stock Crashed Today", "publisher": "Motley Fool",
         "link": "https://example.com/pags", "providerPublishTime": 1792000000, "relatedTickers": ["PAGS", "NVDA"]},
        {"uuid": "n1", "title": "Nvidia could exploit loophole in China", "publisher": "Barron's",
         "link": "https://example.com/nvda", "providerPublishTime": 1792000000, "relatedTickers": ["NVDA"]},
        {"uuid": "n2", "title": "Is NVDA still a buy?", "publisher": "Reuters",
         "link": "https://example.com/nvda2", "providerPublishTime": 1792000000, "relatedTickers": ["NVDA"]},
    ])
    result = yahoo.fetch_news("NVDA", name="NVIDIA Corporation")
    assert [item["uuid"] for item in result["items"]] == ["n1", "n2"]


def test_company_aliases_count_as_naming_the_company():
    assert yahoo.mentions_company("Google cloud wins a bank deal", "GOOGL", "Alphabet Inc.")
    assert yahoo.mentions_company("Bill Gates on Meta's new model", "META", "Meta Platforms, Inc.")
    assert not yahoo.mentions_company("Bill Gates on Meta's new model", "MSFT", "Microsoft Corporation")


def test_saved_article_dates_use_the_local_day(monkeypatch):
    """QA round 2: an article published at 16:07 UTC on 26 Oct (00:07 SGT, 27 Oct) was saved as 26 Oct."""
    from analytics.formatting import format_date

    monkeypatch.setenv("NIMBUS_TIMEZONE", "Asia/Singapore")
    assert format_date("2026-10-26T16:07:00Z") == "27 Oct 2026"
    assert format_date("2026-10-26") == "26 Oct 2026"  # plain dates are never shifted


def test_meeting_date_defaults_to_the_local_day(monkeypatch):
    """QA round 2: at 00:17 SGT on 27 Oct the meeting date defaulted to 26 Oct (the server's UTC day)."""
    import config

    monkeypatch.setenv("NIMBUS_TIMEZONE", "Asia/Singapore")
    monkeypatch.setattr(config, "datetime", _FrozenDatetime)
    assert config.local_today() == date(2026, 10, 27)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        moment = datetime(2026, 10, 26, 16, 17, tzinfo=timezone.utc)  # 00:17 SGT on 27 Oct
        return moment.astimezone(tz) if tz else moment


def test_invalid_date_range_shows_only_the_error():
    """QA round 2: the old results table stayed visible under the date error."""
    briefing_store.save_discussion(make_briefing(), make_note())
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    date_inputs = [d for d in app.date_input if d.label.startswith("Discussion")]
    date_inputs[0].set_value(date(2026, 10, 28))
    date_inputs[1].set_value(date(2026, 10, 27))
    button(app, "Search").click().run()
    assert any("after “Discussion to”" in e.value for e in app.error)
    assert not [s for s in app.selectbox if s.label == "Choose a saved discussion"]


def test_sidebar_shows_version_and_server_start_time():
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    captions = [c.value for c in app.sidebar.caption]
    assert any(c.startswith("Nimbus 0.10.0") and "server started" in c for c in captions), captions
