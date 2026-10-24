"""Saving, searching and reopening briefings (Features 3, 4 and 5)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import fake_yahoo
from models.briefing import RmNote
from services import yahoo
from services.briefing_builder import build_briefing
from storage import briefing_store, database, snapshots


def make_briefing(tickers=("AAPL", "MSFT")):
    return build_briefing(list(tickers), "1 year", "1y", yahoo.fetch_price_history, yahoo.fetch_company_data)


def make_note(reference="Acme Holdings Q4"):
    return RmNote(reference, "2026-10-24", "Discussed results", "Liquidity", "Send deck", "2026-11-30", "",
                  "2026-10-24T13:00:00Z")


def test_save_writes_files_and_all_three_tables(isolated_environment):
    briefing = make_briefing()
    result = briefing_store.save_briefing(briefing, make_note())
    assert result.created
    assert (isolated_environment / result.filename).exists()
    assert (isolated_environment / result.filename.replace(".md", ".json")).exists()
    assert database.count_rows() == {"briefings": 1, "briefing_tickers": 2, "rm_notes": 1}
    note_row = database.get_note(briefing.briefing_id)
    assert note_row["discussion_summary"] == "Discussed results"


def test_saving_twice_creates_one_record():
    briefing = make_briefing()
    assert briefing_store.save_briefing(briefing, make_note()).created
    assert not briefing_store.save_briefing(briefing, make_note()).created
    assert database.count_rows()["briefings"] == 1


def test_database_failure_removes_the_files(isolated_environment, monkeypatch):
    def broken_insert(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(database, "insert_briefing", broken_insert)
    with pytest.raises(RuntimeError):
        briefing_store.save_briefing(make_briefing(), make_note())
    assert not list(isolated_environment.glob("*.md"))
    assert not list(isolated_environment.glob("*.json"))


def test_search_by_ticker_date_reference_and_type():
    first = make_briefing(("AAPL", "MSFT"))
    briefing_store.save_briefing(first, make_note("Acme Holdings Q4"))
    second = make_briefing(("AAPL",))
    briefing_store.save_briefing(second, make_note("Borcelle annual review"))

    assert {r["briefing_id"] for r in database.search_briefings(ticker="aapl")} == {
        first.briefing_id, second.briefing_id}
    assert [r["briefing_id"] for r in database.search_briefings(ticker="MSFT")] == [first.briefing_id]
    assert database.search_briefings(ticker="MU") == []
    assert [r["briefing_id"] for r in database.search_briefings(client_reference="borcelle")] == [
        second.briefing_id]
    today = date.today()
    assert len(database.search_briefings(date_from=today - timedelta(days=1), date_to=today + timedelta(days=1))) == 2
    assert database.search_briefings(date_to=today - timedelta(days=30)) == []
    assert len(database.search_briefings(analysis_type="company_briefing")) == 2
    assert database.search_briefings(analysis_type="news") == []


def test_reopen_returns_the_saved_snapshot_without_calling_yahoo():
    briefing = make_briefing()
    briefing_store.save_briefing(briefing, make_note())
    calls_before = fake_yahoo.total_calls()

    reopened, row = briefing_store.open_briefing(briefing.briefing_id)

    assert fake_yahoo.total_calls() == calls_before
    assert reopened.companies == briefing.companies
    assert reopened.price_index == briefing.price_index
    assert reopened.holding_period_returns == briefing.holding_period_returns
    assert reopened.note.client_reference == "Acme Holdings Q4"
    assert reopened.saved_at is not None
    assert row["tickers"] == "AAPL, MSFT"


def test_markdown_file_contains_comparison_news_sources_and_note(isolated_environment):
    result = briefing_store.save_briefing(make_briefing(), make_note())
    text = (isolated_environment / result.filename).read_text()
    assert "| Revenue growth (YoY) | 6.4% | 15.1% |" in text
    assert "| Debt-to-assets | 27.8% | N/A |" in text
    assert "https://finance.yahoo.com/news/apple-1.html" in text
    assert "Acme Holdings Q4" in text and "Send deck" in text


def test_snapshot_reader_refuses_paths_outside_the_data_folder():
    with pytest.raises(ValueError):
        snapshots.read_snapshot("../secrets.json")
    with pytest.raises(ValueError):
        snapshots.read_snapshot("notes.txt")
