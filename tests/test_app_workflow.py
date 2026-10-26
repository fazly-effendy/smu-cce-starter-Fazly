"""End-to-end acceptance test: drives the real Streamlit app (src/app.py).

Yahoo Finance is replaced by tests/fake_yahoo.py, so this proves the workflow,
storage and search, but not live data access. Run the manual checklist in the
README for that.

test_instructor_acceptance_test follows the instructor's acceptance test
(27 Oct 2026) step by step. Step 12 (the same on Amazon RDS) is run on AWS; the
same suite also runs against MySQL with NIMBUS_TEST_DATABASE_URL.
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


def set_client(app: AppTest, client_id: str = "C-1001", name: str = "") -> AppTest:
    """Step 1: enter a new client ID (and optionally a name) at the top of the page."""
    app.text_input(key="new_client_id").set_value(client_id)
    if name:
        app.text_input(key="new_client_name").set_value(name)
    app.run()
    assert not app.exception, app.exception
    return app


def add_companies(app: AppTest, text: str) -> AppTest:
    """Type into the company search box and press Enter."""
    text_input(app, "Find companies").set_value(text).run()
    assert not app.exception, app.exception
    return app


def generate(app: AppTest, tickers: str) -> AppTest:
    add_companies(app, tickers)
    button(app, "Generate comparison").click().run()
    assert not app.exception, app.exception
    return app


def fill_note(app: AppTest, interests: str = "Dividend income and AI exposure", notes: str = "") -> None:
    key = app.session_state["briefing"].briefing_id
    app.text_area(key=f"interests_{key}").set_value(interests)
    if notes:
        app.text_area(key=f"notes_{key}").set_value(notes)


def save_in_tab(app: AppTest) -> AppTest:
    app.button(key="notes_save").click().run()
    assert not app.exception, app.exception
    return app


def comparison_values(app: AppTest):
    return app.table[0].value  # first table on the page is the financial comparison


def search_and_open(app: AppTest, client: str = None, company: str = "") -> AppTest:
    """History tab: filter by client and/or company, then open the first result."""
    if client:
        app.selectbox(key="history_client").set_value(client)
    app.text_input(key="history_company").set_value(company)
    button(app, "Search").click().run()
    button(app, "Open discussion").click().run()
    assert not app.exception, app.exception
    return app


def saved_values_table(app: AppTest) -> pd.DataFrame:
    """The 'Values at the time of the discussion' table (read from discussion_companies)."""
    return next(t.value for t in app.table if "Stock price at discussion" in t.value.index)


def test_instructor_acceptance_test(isolated_environment):
    # 1. Select or enter a Client ID
    app = set_client(start_app(), "c-1001", "Acme Holdings")

    # 2-3. Enter at least two tickers and generate the comparison
    generate(app, " aapl, MSFT ,aapl ")
    briefing = app.session_state["briefing"]
    assert briefing.successful_tickers == ["AAPL", "MSFT"]  # trimmed, upper-cased, de-duplicated

    # 4. Stock-price performance side by side: rebased chart data, returns and prices per company
    assert set(briefing.price_index) == {"AAPL", "MSFT"}
    assert all(next(iter(series.values())) == 100.0 for series in briefing.price_index.values())
    assert [m.delta for m in app.metric] == ["14.5% over 1 year", "-7.0% over 1 year"]
    assert any("Share-price performance, side by side" in m.value for m in app.markdown)

    # 5. Revenue growth, profit margin and debt-to-equity, plus trends over time
    table = comparison_values(app)
    assert table.loc["Revenue growth (YoY)", "AAPL"] == "6.4%"
    assert table.loc["Revenue growth (YoY)", "MSFT"] == "15.1%"
    assert table.loc["Net profit margin", "MSFT"] == "35.8%"
    assert table.loc["Debt-to-equity", "AAPL"] == "1.43x"
    assert table.loc["Debt-to-equity", "MSFT"] == "N/A"  # not reported: never shown as zero
    assert any("Trends over time" in m.value for m in app.markdown)
    trend = next(t.value for t in app.table if list(t.value.index) == ["AAPL", "MSFT"])
    assert len(trend.columns) >= 2  # several fiscal years

    # 6. Notes about the client's interests
    fill_note(app, "Dividend income and AI exposure", "Discussed FY results and capex plans")
    calls_before_save = fake_yahoo.data_calls()

    # 7. Save the discussion snapshot (exactly once, without refetching data)
    save_in_tab(app)
    assert any("discussion snapshot was saved" in s.value for s in app.success)
    assert not any(b.key == "notes_save" for b in app.button)  # cannot save again
    app.run()
    assert fake_yahoo.data_calls() == calls_before_save
    assert database.count_rows() == {"clients": 1, "discussions": 1, "discussion_companies": 2}
    row = database.search_discussions()[0]
    assert (row["client_id"], row["client_name"]) == ("C-1001", "Acme Holdings")
    assert row["client_interests"] == "Dividend income and AI exposure"
    assert (isolated_environment / row["filename"]).exists()  # Markdown copy on disk / EBS

    # 8. Search by Client ID and reopen it (no Yahoo calls)
    calls_before_reopen = fake_yahoo.data_calls()
    search_and_open(app, client="C-1001")
    assert fake_yahoo.data_calls() == calls_before_reopen
    assert any("Historical snapshot" in i.value for i in app.info)
    page_text = " ".join(m.value for m in app.markdown)
    assert "C-1001" in page_text and "Dividend income and AI exposure" in page_text

    # 10. Reopened values match the saved snapshot: the database rows and the comparison
    saved = saved_values_table(app)
    for company in briefing.companies:
        assert saved.loc["Stock price at discussion", company.ticker] == f"${company.last_close:,.2f}"
    assert saved.loc["Revenue growth (YoY)", "AAPL"] == "6.4%"
    assert saved.loc["Debt-to-equity", "AAPL"] == "1.43x"
    historical_table = [t.value for t in app.table if "Revenue growth (YoY)" in t.value.index
                        and "P/E (trailing)" in t.value.index][-1]
    assert historical_table.equals(table)

    # 9. Search by ticker (any case) and reopen it
    search_and_open(app, company="msft")
    assert any("Historical snapshot" in i.value for i in app.info)

    # 11. Restart Streamlit (new session, same database) and retrieve again, both ways
    restarted = start_app()
    assert restarted.session_state["briefing"] is None
    calls_before_restart = fake_yahoo.data_calls()
    search_and_open(restarted, client="C-1001")
    assert "Dividend income and AI exposure" in " ".join(m.value for m in restarted.markdown)
    search_and_open(restarted, company="Apple")  # by company name as well as ticker
    assert saved_values_table(restarted).equals(saved)
    assert fake_yahoo.data_calls() == calls_before_restart


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


def test_save_requires_a_client_and_the_clients_interests():
    app = generate(start_app(), "AAPL, MSFT")
    save_in_tab(app)
    error = " ".join(e.value for e in app.error)
    assert "a client" in error and "client's interests" in error
    set_client(app, "C 1001")  # invalid: contains a space
    fill_note(app)
    save_in_tab(app)
    assert any("a client" in e.value for e in app.error)
    assert database.count_rows()["discussions"] == 0


def test_saved_client_can_be_chosen_next_time():
    app = set_client(start_app(), "C-2002", "Borcelle")
    generate(app, "AAPL, MSFT")
    fill_note(app)
    save_in_tab(app)
    assert app.session_state["client_choice"] == "C-2002"  # the new client is now selected
    restarted = start_app()
    options = restarted.selectbox(key="client_choice").options
    assert any(o.startswith("C-2002 · Borcelle") for o in options)


def test_typing_a_note_does_not_refetch_data():
    app = generate(start_app(), "AAPL, MSFT")
    calls = fake_yahoo.data_calls()
    key = app.session_state["briefing"].briefing_id
    app.text_area(key=f"interests_{key}").set_value("typing...")
    app.run()
    app.run()
    assert fake_yahoo.data_calls() == calls


@pytest.mark.parametrize("tickers", ["AAPL, MSFT"])
def test_regenerating_within_cache_window_reuses_data(tickers):
    app = generate(start_app(), tickers)
    calls = fake_yahoo.data_calls()
    button(app, "Generate comparison").click().run()
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


def test_recent_discussions_in_sidebar_open_the_saved_discussion():
    app = generate(set_client(start_app()), "AAPL, MSFT")
    key = app.session_state["briefing"].briefing_id
    fill_note(app)
    save_in_tab(app)
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
    assert len(charts) == 5  # price chart + 3 trend charts + ratings bar


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

    set_client(app)
    fill_note(app)
    save_in_tab(app)
    assert not any("Save to note" in b.label for b in app.button)  # read-only once saved

    row = database.search_discussions()[0]
    text = (isolated_environment / row["filename"]).read_text()
    assert "**Saved articles**" in text and "[Microsoft cloud revenue rises](https://example.com/msft-cloud)" in text

    restarted = search_and_open(start_app(), company="MSFT")
    assert "Saved articles" in " ".join(m.value for m in restarted.markdown)


def test_header_shows_unsaved_until_saved_then_save_button_saves_and_toasts():
    app = generate(set_client(start_app()), "AAPL, MSFT")
    assert any("Unsaved discussion" in m.value for m in app.markdown)
    fill_note(app)
    next(b for b in app.button if b.key == "header_save").click().run()
    assert database.count_rows()["discussions"] == 1
    assert any("✓ Saved" in m.value for m in app.markdown)
    assert not any(b.key == "header_save" for b in app.button)
    assert [t.value for t in app.toast][0] == "Discussion with C-1001 saved"
    recent = [b.label for b in app.sidebar.button if b.key and b.key.startswith("recent_")]
    assert len(recent) == 1 and recent[0].startswith("C-1001 · AAPL, MSFT")  # in the sidebar straight away


def test_header_save_with_empty_note_opens_the_dialog():
    app = generate(set_client(start_app()), "AAPL, MSFT")
    next(b for b in app.button if b.key == "header_save").click().run()
    assert database.count_rows()["discussions"] == 0
    key = app.session_state["briefing"].briefing_id
    app.text_area(key=f"dlg_interests_{key}").set_value("From the dialog")
    next(b for b in app.button if b.label == "💾 Save discussion" and b.key not in ("notes_save", "header_save")).click().run()
    assert database.count_rows()["discussions"] == 1
    assert database.search_discussions()[0]["client_interests"] == "From the dialog"


def test_dialog_carries_over_what_was_typed_in_the_discussion_tab():
    app = generate(start_app(), "AAPL, MSFT")  # no client yet, so the note is incomplete
    key = app.session_state["briefing"].briefing_id
    app.text_area(key=f"interests_{key}").set_value("Typed in the tab")
    next(b for b in app.button if b.key == "header_save").click().run()
    assert app.text_area(key=f"dlg_interests_{key}").value == "Typed in the tab"
    assert any("none chosen yet" in m.value for m in app.markdown)


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


def page_layout(app: AppTest):
    """Types of the page's top-level elements, in order. The tabs come last."""
    return [getattr(node, "type", type(node).__name__) for node in app.main.children.values()]


def test_tabs_keep_their_place_between_runs(isolated_environment):
    """Regression: Streamlit 1.50 (EC2) resets the tabs to Compare, and drops half-typed notes,
    when the number of elements above the tabs changes between runs. QA saw this after
    generating a briefing (the spinner), and the save dialog and errors could do the same."""
    app = start_app()
    before = page_layout(app)

    add_companies(app, "AAPL")
    button(app, "Generate comparison").click().run()  # error: needs two companies
    assert page_layout(app) == before

    generate(app, "MSFT")
    after_generate = page_layout(app)
    assert after_generate == before

    fill_note(app, "Acme Q4")  # first note edit
    app.run()
    assert page_layout(app) == after_generate

    next(b for b in app.button if b.key == "header_save").click().run()  # no client yet: opens the dialog
    assert not app.exception, app.exception
    assert page_layout(app) == after_generate
