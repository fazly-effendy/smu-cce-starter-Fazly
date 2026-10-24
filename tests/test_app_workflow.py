"""End-to-end acceptance test: drives the real Streamlit app (src/app.py).

Yahoo Finance is replaced by tests/fake_yahoo.py, so this proves the workflow,
storage and search, but not live data access. Run the manual checklist in the
README for that.

Steps follow the prototype acceptance test agreed for Nimbus.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import fake_yahoo
from storage import database

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


def start_app() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    return app


def button(app: AppTest, label: str):
    matches = [b for b in app.button if b.label == label]
    assert matches, f"No button labelled {label!r}; found {[b.label for b in app.button]}"
    return matches[0]


def text_input(app: AppTest, label_start: str):
    return next(w for w in app.text_input if w.label.startswith(label_start))


def generate(app: AppTest, tickers: str) -> AppTest:
    text_input(app, "Companies").set_value(tickers)
    button(app, "Generate briefing").click().run()
    assert not app.exception, app.exception
    return app


def comparison_values(app: AppTest):
    return app.table[0].value  # first table on the page is the financial comparison


def search_and_open(app: AppTest, ticker: str) -> AppTest:
    text_input(app, "Ticker").set_value(ticker)
    button(app, "Search").click().run()
    button(app, "Open briefing").click().run()
    assert not app.exception, app.exception
    return app


def test_acceptance_workflow(isolated_environment):
    # Steps 2-3: start the app
    app = start_app()
    assert app.title[0].value.endswith("Nimbus")

    # Steps 4-5: two tickers, generate the briefing
    generate(app, " aapl, MSFT ,aapl ")
    briefing = app.session_state["briefing"]
    assert briefing.successful_tickers == ["AAPL", "MSFT"]  # trimmed, upper-cased, de-duplicated

    # Step 6: normalized price comparison (data behind the chart) and returns
    assert set(briefing.price_index) == {"AAPL", "MSFT"}
    assert all(next(iter(series.values())) == 100.0 for series in briefing.price_index.values())
    assert [m.delta for m in app.metric if m.delta] == ["14.5% · 1 year", "-7.0% · 1 year"]
    assert [m.value for m in app.metric if m.label == "P/E (trailing)"] == ["33.5x", "N/A"]
    assert set(briefing.price_history) == {"AAPL", "MSFT"}  # actual prices for chart tooltips

    # Step 7: normalized financial comparison, formatted, N/A for missing inputs
    table = comparison_values(app)
    assert table.loc["Revenue growth (YoY)", "AAPL"] == "6.4%"
    assert table.loc["Net profit margin", "MSFT"] == "35.8%"
    assert table.loc["Market capitalisation", "AAPL"] == "$3.50T"
    assert table.loc["Debt-to-assets", "MSFT"] == "N/A"
    assert table.loc["P/E ratio (trailing)", "MSFT"] == "N/A"

    # Formatted statements (Feature 1): no raw 12-digit numbers
    statements = app.table[1].value
    assert statements.loc["Revenue"].iloc[0] == "$416.00B"

    # Step 8: sourced news with clickable links, publisher and date
    news_markdown = " ".join(m.value for m in app.markdown)
    assert "(https://finance.yahoo.com/news/apple-1.html)" in news_markdown
    assert "Reuters · 20 Oct 2026" in news_markdown
    assert "\\$AAPL" in news_markdown  # dollar sign escaped, not rendered as maths

    # Step 9: RM note
    key = briefing.briefing_id
    app.text_input(key=f"ref_{key}").set_value("Acme Holdings Q4 review")
    app.text_area(key=f"summary_{key}").set_value("Discussed FY results and capex plans")
    app.text_area(key=f"actions_{key}").set_value("Send comparison deck by Friday")
    calls_before_save = fake_yahoo.total_calls()

    # Step 10: save exactly once
    button(app, "Save briefing and RM notes").click().run()
    assert not app.exception, app.exception
    assert any("saved as" in s.value for s in app.success)
    assert "Save briefing and RM notes" not in [b.label for b in app.button]  # cannot save again
    app.run()  # an extra rerun must not create a duplicate
    assert fake_yahoo.total_calls() == calls_before_save  # saving does not refetch data

    # Step 11: records exist in SQLite
    assert database.count_rows() == {"briefings": 1, "briefing_tickers": 2, "rm_notes": 1}
    row = database.search_briefings()[0]
    assert row["client_reference"] == "Acme Holdings Q4 review"
    assert (isolated_environment / row["filename"]).exists()

    # Steps 12-14: search by ticker, reopen, values match the snapshot, no new Yahoo calls
    calls_before_reopen = fake_yahoo.total_calls()
    search_and_open(app, "msft")
    assert fake_yahoo.total_calls() == calls_before_reopen
    assert any("Historical snapshot" in i.value for i in app.info)
    page_text = " ".join(m.value for m in app.markdown)
    assert "Discussed FY results and capex plans" in page_text
    assert "Send comparison deck by Friday" in page_text
    historical_table = app.table[-4].value  # comparison table inside the reopened briefing
    assert historical_table.equals(table)

    # Steps 15-16: restart (new session, same database and files), search and reopen again
    restarted = start_app()
    assert restarted.session_state["briefing"] is None
    calls_before_restart_reopen = fake_yahoo.total_calls()
    search_and_open(restarted, "AAPL")
    assert fake_yahoo.total_calls() == calls_before_restart_reopen
    assert any("Historical snapshot" in i.value for i in restarted.info)
    assert "Acme Holdings Q4 review" in " ".join(m.value for m in restarted.markdown)


def test_invalid_ticker_is_reported_and_valid_ones_continue():
    # Step 17
    app = generate(start_app(), "AAPL, ZZZZ, MSFT")
    notice = [e for e in app.expander if "not included" in e.label]
    assert len(notice) == 1 and "1 entry was not included" in notice[0].label
    assert "ZZZZ" in notice[0].markdown[0].value
    assert not app.warning  # one collapsible notice instead of stacked warning boxes
    assert app.session_state["briefing"].successful_tickers == ["AAPL", "MSFT"]
    assert list(comparison_values(app).columns) == ["AAPL", "MSFT"]


def test_all_tickers_invalid_shows_error_without_crashing():
    app = generate(start_app(), "ZZZZ, YYYY")
    assert any("None of the companies" in e.value for e in app.error)


def test_fewer_than_two_tickers_is_refused():
    app = generate(start_app(), "AAPL")
    assert any("at least two" in e.value for e in app.error)
    assert app.session_state["briefing"] is None


def test_note_requires_reference_and_summary():
    app = generate(start_app(), "AAPL, MSFT")
    button(app, "Save briefing and RM notes").click().run()
    assert any("client or briefing reference" in e.value for e in app.error)
    assert database.count_rows()["briefings"] == 0


def test_typing_a_note_does_not_refetch_data():
    app = generate(start_app(), "AAPL, MSFT")
    calls = fake_yahoo.total_calls()
    key = app.session_state["briefing"].briefing_id
    app.text_area(key=f"summary_{key}").set_value("typing...")
    app.run()
    app.run()
    assert fake_yahoo.total_calls() == calls


@pytest.mark.parametrize("tickers", ["AAPL, MSFT"])
def test_regenerating_within_cache_window_reuses_data(tickers):
    app = generate(start_app(), tickers)
    calls = fake_yahoo.total_calls()
    button(app, "Generate briefing").click().run()
    assert fake_yahoo.total_calls() == calls  # served from the 15-minute cache


def test_company_names_and_full_stop_separators_are_understood():
    app = generate(start_app(), "Apple . Microsoft")
    assert app.session_state["briefing"].successful_tickers == ["AAPL", "MSFT"]
    assert any("Apple → **AAPL**" in c.value for c in app.caption)


def test_misspelt_company_gets_a_suggestion():
    app = generate(start_app(), "AAPL, MSFT, Microsft")  # misspelt: treated as a symbol, not found
    notice = next(e for e in app.expander if "not included" in e.label)
    assert "**MICROSFT**" in notice.markdown[0].value
    assert "Did you mean **MSFT**?" in notice.markdown[0].value


def test_preview_badges_show_parsed_tickers_before_generating():
    app = start_app()
    text_input(app, "Companies").set_value("Apple, msft; Nvidia").run()
    preview = next(m.value for m in app.markdown if m.value.startswith("Will compare:"))
    assert ":blue-badge[AAPL]" in preview and ":blue-badge[MSFT]" in preview and ":blue-badge[NVDA]" in preview
    assert app.session_state["briefing"] is None  # previewing does not retrieve any data
    assert fake_yahoo.total_calls() == 0


def test_quick_add_appends_a_ticker():
    app = start_app()
    next(b for b in app.button if b.key == "quick_NVDA").click().run()
    assert app.session_state["ticker_text"] == "AAPL, MSFT, NVDA"


def test_single_company_shows_add_another_prompt():
    app = generate(start_app(), "AAPL, ZZZZ")
    assert any("Add another ticker to compare" in m.value for m in app.markdown)


def test_recent_briefings_in_sidebar_open_the_saved_briefing():
    app = generate(start_app(), "AAPL, MSFT")
    key = app.session_state["briefing"].briefing_id
    app.text_input(key=f"ref_{key}").set_value("Sidebar check")
    app.text_area(key=f"summary_{key}").set_value("Summary")
    button(app, "Save briefing and RM notes").click().run()
    recent = [b for b in app.sidebar.button if b.key and b.key.startswith("recent_")]
    assert len(recent) == 1
    recent[0].click().run()
    assert app.session_state["open_briefing_id"] == key
    assert any("Historical snapshot" in i.value for i in app.info)
