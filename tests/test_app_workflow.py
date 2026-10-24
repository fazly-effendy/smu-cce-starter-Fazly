"""End-to-end acceptance test: drives the real Streamlit app (src/app.py).

Yahoo Finance is replaced by tests/fake_yahoo.py, so this proves the workflow,
storage and search, but not live data access. Run the manual checklist in the
README for that.

Steps follow the prototype acceptance test agreed for Nimbus.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
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


def add_companies(app: AppTest, text: str) -> AppTest:
    """Type into the company search box and press Enter."""
    text_input(app, "Find companies").set_value(text).run()
    assert not app.exception, app.exception
    return app


def generate(app: AppTest, tickers: str) -> AppTest:
    add_companies(app, tickers)
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
    assert any('class="nb-title">Nimbus<' in m.value for m in app.markdown)

    # Steps 4-5: two tickers, generate the briefing
    generate(app, " aapl, MSFT ,aapl ")
    briefing = app.session_state["briefing"]
    assert briefing.successful_tickers == ["AAPL", "MSFT"]  # trimmed, upper-cased, de-duplicated

    # Step 6: normalized price comparison (data behind the chart) and returns
    assert set(briefing.price_index) == {"AAPL", "MSFT"}
    assert all(next(iter(series.values())) == 100.0 for series in briefing.price_index.values())
    assert [m.delta for m in app.metric] == ["14.5% over 1 year", "-7.0% over 1 year"]
    cards = [m.value for m in app.markdown if 'class="nb-stats"' in m.value]
    assert "33.5x" in cards[0] and "$3.50T" in cards[0] and "N/A" in cards[1]
    assert set(briefing.price_history) == {"AAPL", "MSFT"}  # actual prices for chart tooltips

    # Step 7: normalized financial comparison, formatted, N/A for missing inputs
    table = comparison_values(app)
    assert table.loc["Revenue growth (YoY)", "AAPL"] == "6.4%"
    assert table.loc["Net profit margin", "MSFT"] == "35.8%"
    assert table.loc["Market cap", "AAPL"] == "$3.50T"
    assert table.loc["Debt-to-assets", "MSFT"] == "N/A"
    assert table.loc["P/E (trailing)", "MSFT"] == "N/A"
    assert table.loc["Price date", "AAPL"] == "12 Oct 2026"  # date on its own row, not wrapped next to the price

    # Formatted statements (Feature 1): no raw 12-digit numbers
    statements = app.table[1].value
    assert statements.loc["Revenue"].iloc[0] == "$416.00B"

    # Step 8: sourced news with clickable links, publisher and date
    news_markdown = " ".join(m.value for m in app.markdown)
    assert "(https://finance.yahoo.com/news/apple-1.html)" in news_markdown
    assert 'nb-chip accent">AAPL</span> · Reuters · ' in news_markdown and " ago" in news_markdown
    assert "\\$AAPL" in news_markdown  # dollar sign escaped, not rendered as maths

    # Step 9: RM note
    key = briefing.briefing_id
    app.text_input(key=f"ref_{key}").set_value("Acme Holdings Q4 review")
    app.text_area(key=f"summary_{key}").set_value("Discussed FY results and capex plans")
    app.text_area(key=f"actions_{key}").set_value("Send comparison deck by Friday")
    calls_before_save = fake_yahoo.data_calls()

    # Step 10: save exactly once
    button(app, "💾 Save briefing and RM notes").click().run()
    assert not app.exception, app.exception
    assert any("saved as" in s.value for s in app.success)
    assert "💾 Save briefing and RM notes" not in [b.label for b in app.button]  # cannot save again
    app.run()  # an extra rerun must not create a duplicate
    assert fake_yahoo.data_calls() == calls_before_save  # saving does not refetch data

    # Step 11: records exist in SQLite
    assert database.count_rows() == {"briefings": 1, "briefing_tickers": 2, "rm_notes": 1}
    row = database.search_briefings()[0]
    assert row["client_reference"] == "Acme Holdings Q4 review"
    assert (isolated_environment / row["filename"]).exists()

    # Steps 12-14: search by ticker, reopen, values match the snapshot, no new Yahoo calls
    calls_before_reopen = fake_yahoo.data_calls()
    search_and_open(app, "msft")
    assert fake_yahoo.data_calls() == calls_before_reopen
    assert any("Historical snapshot" in i.value for i in app.info)
    page_text = " ".join(m.value for m in app.markdown)
    assert "Discussed FY results and capex plans" in page_text
    assert "Send comparison deck by Friday" in page_text
    historical_table = [t.value for t in app.table if "Revenue growth (YoY)" in t.value.index][-1]
    assert historical_table.equals(table)  # comparison table inside the reopened briefing

    # Steps 15-16: restart (new session, same database and files), search and reopen again
    restarted = start_app()
    assert restarted.session_state["briefing"] is None
    calls_before_restart_reopen = fake_yahoo.data_calls()
    search_and_open(restarted, "AAPL")
    assert fake_yahoo.data_calls() == calls_before_restart_reopen
    assert any("Historical snapshot" in i.value for i in restarted.info)
    assert "Acme Holdings Q4 review" in " ".join(m.value for m in restarted.markdown)


def test_invalid_ticker_is_reported_and_valid_ones_continue():
    # Step 17
    app = generate(start_app(), "AAPL, ZZZZ, MSFT")
    notice = [e for e in app.expander if "not included" in e.label]
    assert len(notice) == 1 and "1 company was not included" in notice[0].label
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
    button(app, "💾 Save briefing and RM notes").click().run()
    assert any("client or briefing reference" in e.value for e in app.error)
    assert database.count_rows()["briefings"] == 0


def test_typing_a_note_does_not_refetch_data():
    app = generate(start_app(), "AAPL, MSFT")
    calls = fake_yahoo.data_calls()
    key = app.session_state["briefing"].briefing_id
    app.text_area(key=f"summary_{key}").set_value("typing...")
    app.run()
    app.run()
    assert fake_yahoo.data_calls() == calls


@pytest.mark.parametrize("tickers", ["AAPL, MSFT"])
def test_regenerating_within_cache_window_reuses_data(tickers):
    app = generate(start_app(), tickers)
    calls = fake_yahoo.data_calls()
    button(app, "Generate briefing").click().run()
    assert fake_yahoo.data_calls() == calls  # served from the 15-minute cache


def test_company_names_and_full_stop_separators_are_understood():
    app = generate(start_app(), "Apple . Microsoft")
    assert app.session_state["briefing"].successful_tickers == ["AAPL", "MSFT"]


def test_misspelt_company_gets_one_short_message_with_suggestion():
    app = add_companies(start_app(), "Microsft")
    assert [w.value for w in app.warning] == [
        "No company found for “Microsft”. Did you mean Microsoft Corporation (MSFT)?"]
    button(app, "Add MSFT").click().run()
    assert app.session_state["selected_tickers"] == ["MSFT"]
    assert not app.warning


def test_partial_name_shows_matches_to_choose_from():
    app = add_companies(start_app(), "nvid")
    assert app.session_state["selected_tickers"] == []  # nothing added until the user chooses
    assert any("NVIDIA Corporation" in m.value and "NASDAQ" in m.value for m in app.markdown)
    next(b for b in app.button if b.key == "pick_0_NVDA").click().run()
    assert app.session_state["selected_tickers"] == ["NVDA"]
    assert app.session_state["companies"]["NVDA"].exchange == "NASDAQ"


def test_ambiguous_name_is_chosen_automatically_and_can_be_switched():
    app = add_companies(start_app(), "Google")
    assert app.session_state["selected_tickers"] == ["GOOGL"]
    assert any("typed “Google”" in m.value for m in app.markdown)
    switch = app.selectbox(key="switch_GOOGL")
    switch.set_value("GOOG").run()
    assert app.session_state["selected_tickers"] == ["GOOG"]
    assert [m.ticker for m in app.session_state["alternatives"]["GOOG"]] == ["GOOGL"]


def test_confirmation_row_before_generating_makes_no_data_calls():
    app = add_companies(start_app(), "Apple, msft; Nvidia")
    assert app.session_state["selected_tickers"] == ["AAPL", "MSFT", "NVDA"]
    assert app.multiselect(key="selected_tickers").value == ["AAPL", "MSFT", "NVDA"]
    assert any(m.value == '<span class="nb-chip accent">NVDA</span>' for m in app.markdown)
    assert app.session_state["briefing"] is None
    assert fake_yahoo.data_calls() == 0  # only name searches so far, no market data


def test_removing_a_chip_removes_the_company():
    app = add_companies(start_app(), "AAPL, MSFT, NVDA")
    app.multiselect(key="selected_tickers").unselect("MSFT").run()
    assert app.session_state["selected_tickers"] == ["AAPL", "NVDA"]
    app.multiselect(key="selected_tickers").unselect("AAPL").run()  # a second removal keeps the rest
    assert app.session_state["selected_tickers"] == ["NVDA"]
    add_companies(app, "Palantir")  # adding after removals keeps the existing selection
    next(b for b in app.button if b.key == "pick_0_PLTR").click().run()
    assert app.session_state["selected_tickers"] == ["NVDA", "PLTR"]
    app.multiselect(key="selected_tickers").select("MSFT").run()  # removed companies can be re-added
    assert app.session_state["selected_tickers"] == ["NVDA", "PLTR", "MSFT"]


def test_quick_add_adds_a_company():
    app = start_app()
    next(b for b in app.button if b.key == "quick_NVDA").click().run()
    assert app.session_state["selected_tickers"] == ["NVDA"]


def test_tickers_still_work_when_name_search_is_offline():
    fake_yahoo.SEARCH_ONLINE = False
    app = generate(start_app(), "AAPL, MSFT")
    assert app.session_state["briefing"].successful_tickers == ["AAPL", "MSFT"]


def test_single_company_shows_add_another_prompt():
    app = generate(start_app(), "AAPL, ZZZZ")
    assert any("Add another ticker to compare" in m.value for m in app.markdown)


def test_recent_briefings_in_sidebar_open_the_saved_briefing():
    app = generate(start_app(), "AAPL, MSFT")
    key = app.session_state["briefing"].briefing_id
    app.text_input(key=f"ref_{key}").set_value("Sidebar check")
    app.text_area(key=f"summary_{key}").set_value("Summary")
    button(app, "💾 Save briefing and RM notes").click().run()
    recent = [b for b in app.sidebar.button if b.key and b.key.startswith("recent_")]
    assert len(recent) == 1
    recent[0].click().run()
    assert app.session_state["open_briefing_id"] == key
    assert any("Historical snapshot" in i.value for i in app.info)


def markdown_containing(app: AppTest, text: str) -> str:
    return next(m.value for m in app.markdown if text in m.value)


def dataframe_with(app: AppTest, column: str) -> pd.DataFrame:
    return next(d.value for d in app.dataframe if column in d.value.columns)


def test_analyst_view_shows_consensus_target_and_upside():
    app = generate(start_app(), "AAPL, MSFT")
    frame = dataframe_with(app, "Consensus").set_index("Company")
    assert frame.loc["AAPL", "Consensus"] == "🟢 Buy"
    assert frame.loc["AAPL", "Analysts"] == 40 and frame.loc["AAPL", "Target"] == 251.9
    assert frame.loc["AAPL", "Upside"] == pytest.approx(10.0)  # shown as +10.0%
    assert (frame.loc["AAPL", "Low"], frame.loc["AAPL", "High"]) == (180.0, 300.0)
    assert frame.loc["MSFT"].drop("Ccy").isna().all()  # missing data stays blank, never zero
    charts = app.get("vega_lite_chart") + app.get("arrow_vega_lite_chart")  # element name differs by version
    assert len(charts) == 2  # price chart + ratings bar


def test_earnings_table_shows_next_date_and_beat_or_miss():
    app = generate(start_app(), "AAPL, MSFT")
    frame = dataframe_with(app, "Result").set_index("Company")
    assert frame.loc["MSFT", "Next date"].date() == fake_yahoo.NEXT_EARNINGS
    assert frame.loc["MSFT", "Next EPS est."] == 3.62
    assert (frame.loc["MSFT", "EPS actual"], frame.loc["MSFT", "EPS est."]) == (3.65, 3.35)
    assert frame.loc["MSFT", "Surprise"] == pytest.approx(8.955, abs=0.01)
    assert frame.loc["MSFT", "Result"] == "🟢 Beat"


def test_unusual_values_are_flagged_but_kept(monkeypatch):
    """P/E over 100 and EPS surprise over 100% keep their real values and get a ⚠ marker."""
    monkeypatch.setitem(fake_yahoo.DATA["AAPL"]["info"], "trailingPE", 409.2)
    dates = fake_yahoo.DATA["MSFT"]["earnings_dates"].copy()
    dates.iloc[1, dates.columns.get_loc("Reported EPS")] = 9.11
    dates.iloc[1, dates.columns.get_loc("EPS Estimate")] = 2.90
    monkeypatch.setitem(fake_yahoo.DATA["MSFT"], "earnings_dates", dates)
    app = generate(start_app(), "AAPL, MSFT")
    assert comparison_values(app).loc["P/E (trailing)", "AAPL"] == "409.2x ⚠"
    card = next(m.value for m in app.markdown if 'class="nb-stats"' in m.value and "409.2x" in m.value)
    assert "⚠ unusual" in card and "one-off items" in card  # tooltip text
    earnings = dataframe_with(app, "Result").set_index("Company")
    assert earnings.loc["MSFT", "Result"] == "🟢 Beat ⚠"
    assert earnings.loc["MSFT", "Surprise"] == pytest.approx((9.11 - 2.90) / 2.90 * 100)


def test_comparison_table_bolds_best_value_and_colours_negatives():
    from ui.tables import comparison_styles
    from services.briefing_builder import build_briefing
    from services import yahoo
    briefing = build_briefing(["AAPL", "MSFT"], "1 year", "1y", yahoo.fetch_price_history, yahoo.fetch_company_data)
    styles = comparison_styles(briefing)
    assert "font-weight: 700" in styles.loc["Return (1 year)", "AAPL"]  # 14.5% beats -7.0%
    assert "color" in styles.loc["Return (1 year)", "MSFT"]  # negative shown in red
    assert "font-weight: 700" in styles.loc["Net profit margin", "MSFT"]  # 35.8% beats 26.9%
    assert styles.loc["Debt-to-assets", "AAPL"] == ""  # only one company reports it: nothing to rank


def test_news_feed_is_newest_first_filterable_and_shows_thumbnails():
    app = generate(start_app(), "AAPL, MSFT")
    headlines = [m.value for m in app.markdown if m.value.startswith("**[")]
    assert [h.split("](")[0] for h in headlines] == [
        "**[Microsoft cloud revenue rises", "**[Apple & partners expand \\$AAPL services",
        "**[Analysts review iPhone demand"]
    images = app.get("image") + app.get("imgs")  # element name differs between Streamlit versions
    assert len(images) == 1 and "https://s.yimg.com/apple-170.jpg" in str(images[0].proto)
    app.get("button_group")[0].set_value(["MSFT"]).run()  # company filter
    headlines = [m.value for m in app.markdown if m.value.startswith("**[")]
    assert len(headlines) == 1 and "Microsoft" in headlines[0]


def test_saved_articles_are_stored_with_the_note_and_reopened(isolated_environment):
    app = generate(start_app(), "AAPL, MSFT")
    pin = next(b for b in app.button if b.label == "☆ Save to note")
    pin.click().run()
    assert any(b.label == "★ Saved to note" for b in app.button)
    assert "Microsoft cloud revenue rises" in markdown_containing(app, "Microsoft cloud revenue rises")

    key = app.session_state["briefing"].briefing_id
    app.text_input(key=f"ref_{key}").set_value("Article check")
    app.text_area(key=f"summary_{key}").set_value("Summary")
    button(app, "💾 Save briefing and RM notes").click().run()
    assert not any("Save to note" in b.label for b in app.button)  # read-only once saved

    row = database.search_briefings()[0]
    text = (isolated_environment / row["filename"]).read_text()
    assert "**Saved articles**" in text and "[Microsoft cloud revenue rises](https://example.com/msft-cloud)" in text

    restarted = search_and_open(start_app(), "MSFT")
    assert "Saved articles" in " ".join(m.value for m in restarted.markdown)


def fill_note(app: AppTest, reference: str = "Header save check", summary: str = "Summary") -> None:
    key = app.session_state["briefing"].briefing_id
    app.text_input(key=f"ref_{key}").set_value(reference)
    app.text_area(key=f"summary_{key}").set_value(summary)


def test_header_shows_unsaved_until_saved_then_save_button_saves_and_toasts():
    app = generate(start_app(), "AAPL, MSFT")
    assert any("Unsaved briefing" in m.value for m in app.markdown)
    fill_note(app)
    next(b for b in app.button if b.key == "header_save").click().run()
    assert database.count_rows()["briefings"] == 1
    assert any("✓ Saved" in m.value for m in app.markdown)
    assert not any(b.key == "header_save" for b in app.button)
    assert [t.value for t in app.toast][0].startswith("Briefing saved as ")
    recent = [b.label for b in app.sidebar.button if b.key and b.key.startswith("recent_")]
    assert len(recent) == 1 and recent[0].startswith("AAPL, MSFT")  # in Recent briefings straight away


def test_header_save_with_empty_note_opens_the_note_dialog():
    app = generate(start_app(), "AAPL, MSFT")
    next(b for b in app.button if b.key == "header_save").click().run()
    assert database.count_rows()["briefings"] == 0
    key = app.session_state["briefing"].briefing_id
    app.text_input(key=f"dlg_ref_{key}").set_value("From the dialog")
    app.text_area(key=f"dlg_summary_{key}").set_value("Saved via the header button")
    next(b for b in app.button if b.label == "💾 Save briefing and RM notes" and b.key != "notes_save").click().run()
    assert database.count_rows()["briefings"] == 1
    assert database.search_briefings()[0]["client_reference"] == "From the dialog"


def test_dialog_carries_over_what_was_typed_in_the_notes_tab():
    app = generate(start_app(), "AAPL, MSFT")
    key = app.session_state["briefing"].briefing_id
    app.text_input(key=f"ref_{key}").set_value("Typed in Notes")  # summary still empty
    next(b for b in app.button if b.key == "header_save").click().run()
    assert app.text_input(key=f"dlg_ref_{key}").value == "Typed in Notes"


def test_news_tab_explains_a_failed_fetch_instead_of_no_news():
    fake_yahoo.NEWS_FEED_MODE = "error"
    fake_yahoo.SEARCH_ONLINE = False
    app = generate(start_app(), "AAPL, MSFT")
    warning = next(w.value for w in app.warning if "News could not be retrieved" in w.value)
    assert "**AAPL**: news feed failed (ConnectionError: news feed unreachable)" in warning
    assert "scripts/debug_news.py AAPL MSFT" in warning


def test_news_tab_uses_search_fallback_and_says_so():
    fake_yahoo.NEWS_FEED_MODE = "empty"
    app = generate(start_app(), "AAPL, MSFT")
    headlines = [m.value for m in app.markdown if m.value.startswith("**[")]
    assert headlines == ["**[Apple supplier outlook improves](https://example.com/apple-suppliers)**"]
    captions = " ".join(c.value for c in app.caption)
    assert "AAPL: Yahoo's news feed was empty, so articles come from Yahoo search." in captions
    assert "Yahoo has no recent articles for MSFT." in captions
    assert any(b.label == "☆ Save to note" for b in app.button)
