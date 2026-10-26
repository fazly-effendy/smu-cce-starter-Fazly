"""Saving, searching and reopening client discussions (Features 3, 4 and 5).

Follows the instructor's design (27 Oct 2026): clients -> discussions -> discussion_companies,
retrievable by client and by company, reopened exactly as saved.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

import fake_yahoo
from models.briefing import RmNote
from services import yahoo
from services.briefing_builder import build_briefing
from storage import briefing_store, database, snapshots


def make_briefing(tickers=("AAPL", "MSFT")):
    return build_briefing(list(tickers), "1 year", "1y", yahoo.fetch_price_history, yahoo.fetch_company_data)


def make_note(client_id="C-1001", interests="Dividend income and AI exposure", client_name=None,
              discussion_date="2026-10-24"):
    return RmNote(client_id=client_id, discussion_date=discussion_date, client_interests=interests,
                  notes="Discussed results", follow_up_actions="Send deck", next_review_date="2026-11-30",
                  free_text="", created_at="2026-10-24T13:00:00Z", client_name=client_name)


def test_save_writes_markdown_and_all_three_tables(isolated_environment):
    briefing = make_briefing()
    result = briefing_store.save_discussion(briefing, make_note(client_name="Acme Holdings"))
    assert result.created
    assert (isolated_environment / result.filename).exists()
    assert not list(isolated_environment.glob("*.json"))  # the snapshot lives in the database now
    assert database.count_rows() == {"clients": 1, "discussions": 1, "discussion_companies": 2}
    row = database.get_discussion(briefing.briefing_id)
    assert row["client_id"] == "C-1001" and row["client_name"] == "Acme Holdings"
    assert row["discussion_date"] == date(2026, 10, 24)
    assert row["client_interests"] == "Dividend income and AI exposure"


def test_each_company_row_keeps_the_values_seen_at_the_discussion():
    """Instructor's required fields: ticker and stock price at the time, plus the ratios."""
    briefing = make_briefing()
    briefing_store.save_discussion(briefing, make_note())
    rows = {r["ticker"]: r for r in database.get_companies(briefing.briefing_id)}
    for company in briefing.companies:
        row = rows[company.ticker]
        assert row["stock_price"] == pytest.approx(company.last_close)
        assert row["price_date"] == date.fromisoformat(company.last_close_date)
        assert row["company_name"] == company.name
        for key in ("revenue_growth", "net_margin", "operating_margin", "debt_to_equity"):
            expected = company.ratios.get(key)
            assert row[key] == (pytest.approx(expected) if expected is not None else None), key
        assert row["source"] == yahoo.SOURCE_NAME


def test_saving_twice_creates_one_record():
    briefing = make_briefing()
    assert briefing_store.save_discussion(briefing, make_note()).created
    assert not briefing_store.save_discussion(briefing, make_note()).created
    assert database.count_rows()["discussions"] == 1


def test_one_client_many_discussions_and_the_name_is_filled_in_later():
    briefing_store.save_discussion(make_briefing(), make_note("c-1001 "))  # normalised to C-1001
    briefing_store.save_discussion(make_briefing(("AAPL",)), make_note("C-1001", client_name="Acme Holdings"))
    assert database.count_rows()["clients"] == 1
    assert database.list_clients() == [{"client_id": "C-1001", "client_name": "Acme Holdings", "discussions": 2}]


@pytest.mark.parametrize("client_id, interests", [("", "Income"), ("C 1001", "Income"), ("C-1001", "  ")])
def test_invalid_client_id_or_missing_interests_saves_nothing(isolated_environment, client_id, interests):
    with pytest.raises(ValueError):
        briefing_store.save_discussion(make_briefing(), make_note(client_id, interests))
    assert database.count_rows() == {"clients": 0, "discussions": 0, "discussion_companies": 0}
    assert not list(isolated_environment.glob("*.md"))


def test_database_failure_removes_the_file(isolated_environment, monkeypatch):
    def broken_insert(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(database, "insert_discussion", broken_insert)
    with pytest.raises(RuntimeError):
        briefing_store.save_discussion(make_briefing(), make_note())
    assert not list(isolated_environment.glob("*.md"))


def test_search_by_client_company_and_date():
    first = make_briefing(("AAPL", "MSFT"))
    briefing_store.save_discussion(first, make_note("C-1001", discussion_date="2026-10-20"))
    second = make_briefing(("AAPL",))
    briefing_store.save_discussion(second, make_note("C-2002", discussion_date="2026-10-24"))

    def ids(**filters):
        return [r["discussion_id"] for r in database.search_discussions(**filters)]

    assert ids(client_id="C-1001") == [first.briefing_id]
    assert ids(client_id="c-2002") == [second.briefing_id]
    assert ids(company="aapl") == [second.briefing_id, first.briefing_id]  # newest discussion first
    assert ids(company="MSFT") == [first.briefing_id]
    assert ids(company="microsoft") == [first.briefing_id]  # company name, not just ticker
    assert ids(company="MU") == []
    assert ids(client_id="C-2002", company="MSFT") == []
    assert ids(date_from=date(2026, 10, 21)) == [second.briefing_id]
    assert ids(date_to=date(2026, 10, 20)) == [first.briefing_id]
    rows = database.search_discussions(client_id="C-1001")
    assert rows[0]["tickers"] == "AAPL, MSFT" and "snapshot_json" not in rows[0]


def test_reopen_returns_the_saved_snapshot_without_calling_yahoo():
    briefing = make_briefing()
    briefing_store.save_discussion(briefing, make_note())
    calls_before = fake_yahoo.total_calls()

    reopened, row = briefing_store.open_discussion(briefing.briefing_id)

    assert fake_yahoo.total_calls() == calls_before
    assert reopened.companies == briefing.companies
    assert reopened.price_index == briefing.price_index
    assert reopened.holding_period_returns == briefing.holding_period_returns
    assert reopened.note.client_id == "C-1001"
    assert reopened.note.client_interests == "Dividend income and AI exposure"
    assert reopened.saved_at is not None
    assert row["tickers"] == "AAPL, MSFT"


def test_reopen_works_without_the_markdown_file(isolated_environment):
    """Any app server can reopen any discussion: the snapshot is in the database, not only on disk."""
    briefing = make_briefing()
    result = briefing_store.save_discussion(briefing, make_note())
    (isolated_environment / result.filename).unlink()

    reopened, row = briefing_store.open_discussion(briefing.briefing_id)
    assert reopened.companies == briefing.companies
    markdown = snapshots.markdown_for(reopened, row["filename"])
    assert "C-1001" in markdown and "Dividend income and AI exposure" in markdown


def test_markdown_file_leads_with_the_discussion_fields(isolated_environment):
    result = briefing_store.save_discussion(make_briefing(), make_note())
    text = (isolated_environment / result.filename).read_text()
    assert result.filename.startswith("C-1001__AAPL-MSFT__")
    assert "- **Client ID:** C-1001" in text
    assert "- **Discussion date:** 24 Oct 2026" in text
    assert "Dividend income and AI exposure" in text
    assert "| Revenue growth (YoY) | 6.4% | 15.1% |" in text
    assert "| Debt-to-equity |" in text
    assert "| Stock price at discussion (close) |" in text
    assert "https://finance.yahoo.com/news/apple-1.html" in text
    assert "Send deck" in text


def test_markdown_reader_refuses_paths_outside_the_data_folder():
    with pytest.raises(ValueError):
        snapshots.read_markdown("../secrets.md")
    with pytest.raises(ValueError):
        snapshots.read_markdown("notes.txt")


def test_snapshots_saved_by_older_versions_still_open():
    """Schema 1–3 snapshots have older note field names and lack later fields."""
    briefing = make_briefing()
    briefing_store.save_discussion(briefing, make_note())
    data = json.loads(database.get_discussion(briefing.briefing_id)["snapshot_json"])
    data["schema_version"] = 1
    data.pop("price_history")
    data["note"] = {"client_reference": "C-1001", "meeting_date": "2026-10-24", "discussion_summary": "Old",
                    "client_priorities": "Old interests", "follow_up_actions": "", "next_review_date": None,
                    "free_text": "", "created_at": "2026-10-24T13:00:00Z"}
    for company in data["companies"]:
        company.pop("analyst")
        company.pop("earnings")
        for item in company["news"]:
            item.pop("thumbnail_url")
    with database.get_engine().begin() as connection:
        connection.execute(database.discussions.update()
                           .where(database.discussions.c.discussion_id == briefing.briefing_id)
                           .values(snapshot_json=json.dumps(data)))

    reopened, _ = briefing_store.open_discussion(briefing.briefing_id)
    assert reopened.schema_version == 1
    assert reopened.note.client_id == "C-1001" and reopened.note.client_interests == "Old interests"
    assert reopened.price_history == {} and reopened.note.saved_articles == []
    assert reopened.companies[0].analyst is None and reopened.companies[0].news[0].thumbnail_url is None


def test_today_falls_inside_a_recent_date_range():
    briefing_store.save_discussion(make_briefing(), make_note(discussion_date=date.today().isoformat()))
    today = date.today()
    assert len(database.search_discussions(date_from=today - timedelta(days=1), date_to=today + timedelta(days=1))) == 1
