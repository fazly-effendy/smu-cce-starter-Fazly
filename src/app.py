"""Nimbus: company briefings for relationship managers.

Run with:  python3 -m streamlit run src/app.py

Workflow: generate a briefing for two or more companies -> compare them ->
read financials, news and ratings -> add RM notes -> save -> search history
-> reopen a saved briefing exactly as it was.

This file holds only the user interface. Data retrieval lives in services/,
calculations in analytics/, and saving/searching in storage/.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

from analytics.formatting import (
    NOT_AVAILABLE,
    format_date,
    format_money,
    format_multiple,
    format_percent,
    format_price,
    format_timestamp,
)
from analytics.ratios import RATIO_LABELS
from config import (
    ANALYSIS_PERIODS,
    APP_VERSION,
    CACHE_TTL_SECONDS,
    DEFAULT_PERIOD_LABEL,
    database_url,
    describe_database_url,
)
from models.briefing import ANALYSIS_TYPE, Briefing, RmNote
from services import yahoo
from services.briefing_builder import build_briefing, utc_now_iso
from storage import briefing_store, database, snapshots

st.set_page_config(page_title="Nimbus", page_icon="☁️", layout="wide")


# --------------------------------------------------------------------------
# Cached data retrieval: repeated requests within 15 minutes reuse results
# instead of calling Yahoo again. Typing in other widgets never refetches.
# --------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_price_history(ticker: str, period_code: str) -> pd.Series:
    return yahoo.fetch_price_history(ticker, period_code)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def cached_company_data(ticker: str) -> dict:
    return yahoo.fetch_company_data(ticker)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def md_text(text: Optional[str]) -> str:
    """Escape characters Streamlit Markdown would misread (e.g. $ starts maths)."""
    if not text:
        return ""
    for char in ("\\", "$", "*", "_", "[", "]", "`", "#", "<", ">"):
        text = text.replace(char, "\\" + char)
    return text


def init_state() -> None:
    st.session_state.setdefault("briefing", None)  # the briefing currently on screen
    st.session_state.setdefault("saved", {})  # briefing_id -> saved filename
    st.session_state.setdefault("history_filters", {})
    st.session_state.setdefault("open_briefing_id", None)


# --------------------------------------------------------------------------
# Rendering: used for both the live briefing and reopened historical ones
# --------------------------------------------------------------------------

def render_failures(briefing: Briefing) -> None:
    for ticker, reason in briefing.failed_tickers.items():
        st.warning(f"**{ticker}** was not included: {md_text(reason)}")


def comparison_table(briefing: Briefing) -> pd.DataFrame:
    companies = briefing.companies
    rows = {
        "Last close": [f"{format_price(c.last_close, c.currency)} ({format_date(c.last_close_date)})" for c in companies],
        f"Holding-period return ({briefing.analysis_period})": [
            format_percent(briefing.holding_period_returns.get(c.ticker)) for c in companies
        ],
        "Market capitalisation": [format_money(c.market_cap, c.currency) for c in companies],
        "P/E ratio (trailing)": [format_multiple(c.pe_ratio) for c in companies],
    }
    for key, label in RATIO_LABELS.items():
        rows[label] = [format_percent(c.ratios.get(key)) for c in companies]
    rows["Fiscal year used for ratios"] = [
        f"FY ending {format_date(c.fiscal_year_end)}" if c.fiscal_year_end else NOT_AVAILABLE for c in companies
    ]
    return pd.DataFrame(rows, index=[c.ticker for c in companies]).T


def render_comparison(briefing: Briefing) -> None:
    render_failures(briefing)
    companies = briefing.companies
    if not companies:
        st.info("No company data to show.")
        return
    if len(companies) < 2:
        st.info("Only one company was retrieved, so there is nothing to compare it with yet.")

    columns = st.columns(len(companies))
    for column, company in zip(columns, companies):
        hpr = briefing.holding_period_returns.get(company.ticker)
        column.metric(
            f"{company.name} ({company.ticker})",
            format_price(company.last_close, company.currency),
            delta=f"{format_percent(hpr)} over {briefing.analysis_period}" if hpr is not None else None,
        )

    st.subheader("Financial comparison")
    st.table(comparison_table(briefing))
    with st.expander("How these measures are calculated"):
        st.markdown(
            "- **Revenue / net income growth:** latest fiscal year ÷ previous fiscal year − 1. "
            "N/A if the previous year is zero or negative.\n"
            "- **Net profit margin:** net income ÷ revenue (latest fiscal year).\n"
            "- **Return on assets:** net income ÷ total assets at the same fiscal year-end.\n"
            "- **Debt-to-assets:** total debt ÷ total assets at the same fiscal year-end.\n"
            "- **Holding-period return:** last ÷ first adjusted closing price over the dates all companies "
            "traded; adjusted prices include dividends and splits. Historical, not a forecast.\n"
            "- **N/A** means Yahoo Finance did not report the inputs. Nimbus never substitutes zero.\n"
            "- Companies can have different fiscal year-ends; the row above shows which year each uses."
        )

    st.subheader("Share-price performance (rebased to 100)")
    if briefing.price_index:
        chart = pd.DataFrame(briefing.price_index)
        chart.index = pd.to_datetime(chart.index)
        st.line_chart(chart)
        if briefing.price_window:
            st.caption(
                f"Adjusted closing prices from {format_date(briefing.price_window[0])} to "
                f"{format_date(briefing.price_window[1])}, on dates when every company traded. "
                "Each line starts at 100."
            )
    else:
        st.info("Not enough common trading days to draw a comparison chart.")


def render_financials(briefing: Briefing) -> None:
    if not briefing.companies:
        st.info("No company data to show.")
        return
    for company in briefing.companies:
        st.subheader(f"{company.name} ({company.ticker})")
        if company.financials:
            years = sorted({y for values in company.financials.values() for y in values}, reverse=True)
            table = pd.DataFrame(
                {
                    f"FY {format_date(y)}": [
                        format_money(company.financials[item].get(y), company.financial_currency)
                        for item in company.financials
                    ]
                    for y in years
                },
                index=list(company.financials),
            )
            st.table(table)
        else:
            st.info("Yahoo Finance returned no financial statements for this company.")
        st.caption(
            f"Annual statements. Source: [{company.source_name}]({company.source_url}), "
            f"retrieved {format_timestamp(company.retrieved_at)}. "
            f"Figures in {company.financial_currency or 'the reporting currency'}."
        )


def render_news_and_ratings(briefing: Briefing) -> None:
    if not briefing.companies:
        st.info("No company data to show.")
        return
    for company in briefing.companies:
        st.subheader(f"{company.name} ({company.ticker})")
        ratings = company.ratings
        if ratings:
            labels = [("strongBuy", "Strong buy"), ("buy", "Buy"), ("hold", "Hold"), ("sell", "Sell"),
                      ("strongSell", "Strong sell")]
            counts = [ratings.get(key) for key, _ in labels]
            st.markdown("**Analyst recommendations (number of analysts, current month)**")
            st.table(pd.DataFrame([[c if c is not None else NOT_AVAILABLE for c in counts]],
                                  columns=[label for _, label in labels], index=["Analysts"]))
        else:
            st.caption("No analyst ratings available from Yahoo Finance.")

        st.markdown("**Recent news**")
        if not company.news:
            st.caption("No recent news available from Yahoo Finance.")
        for item in company.news:
            headline = md_text(item.headline)
            title = f"[{headline}]({item.source_url})" if item.source_url else headline
            meta = " · ".join(
                part for part in [md_text(item.publisher), format_date(item.published_at) if item.published_at else ""]
                if part
            )
            st.markdown(f"**{title}**  \n{meta or 'Publisher and date not provided'}")
            st.markdown(md_text(item.summary) if item.summary else "_No summary provided by the source._")
            if not item.source_url:
                st.caption("Source link not provided by Yahoo.")
        for warning in company.warnings:
            st.caption(f"Note: {md_text(warning)}")
        st.divider()


def render_note(note: Optional[RmNote]) -> None:
    if not note:
        st.info("No RM note was saved with this briefing.")
        return
    left, right = st.columns(2)
    left.markdown(f"**Client / briefing reference:** {md_text(note.client_reference)}")
    left.markdown(f"**Meeting date:** {format_date(note.meeting_date)}")
    right.markdown(f"**Next review date:** {format_date(note.next_review_date)}")
    right.markdown(f"**Note recorded:** {format_timestamp(note.created_at)}")
    for label, text in (
        ("Discussion summary", note.discussion_summary),
        ("Client priorities or concerns", note.client_priorities),
        ("Follow-up actions", note.follow_up_actions),
        ("Other notes", note.free_text),
    ):
        st.markdown(f"**{label}**")
        st.markdown(md_text(text) if text else NOT_AVAILABLE)


# --------------------------------------------------------------------------
# Sections of the page
# --------------------------------------------------------------------------

def generate_section() -> None:
    with st.form("generate_form"):
        left, right = st.columns([3, 1])
        tickers_text = left.text_input(
            "Companies (ticker symbols, separated by commas)",
            value="AAPL, MSFT",
            help="Enter at least two tickers, e.g. AAPL, MSFT, MU",
        )
        period_label = right.selectbox(
            "Share-price period",
            list(ANALYSIS_PERIODS),
            index=list(ANALYSIS_PERIODS).index(DEFAULT_PERIOD_LABEL),
        )
        submitted = st.form_submit_button("Generate briefing", type="primary")

    if not submitted:
        return
    tickers, rejected = yahoo.parse_tickers(tickers_text)
    if rejected:
        st.warning("Ignored entries that are not valid ticker symbols: " + ", ".join(rejected))
    if len(tickers) < 2:
        st.error("Enter at least two different ticker symbols to generate a comparison briefing.")
        return

    with st.spinner("Retrieving data from Yahoo Finance…"):
        briefing = build_briefing(
            tickers,
            period_label,
            ANALYSIS_PERIODS[period_label],
            fetch_history=cached_price_history,
            fetch_company=cached_company_data,
        )
    st.session_state["briefing"] = briefing
    if not briefing.companies:
        st.error("None of the tickers could be retrieved. Check the symbols and try again.")


def notes_and_save_section(briefing: Optional[Briefing]) -> None:
    if briefing is None:
        st.info("Generate a briefing first, then record your meeting notes here.")
        return
    saved_filename = st.session_state["saved"].get(briefing.briefing_id)
    if saved_filename:
        st.success(f"This briefing and its RM note were saved as **{saved_filename}**.")
        st.caption("Find it in Briefing history. Generate a new briefing to start another.")
        render_note(st.session_state.get("saved_note"))
        return
    if not briefing.companies:
        st.warning("There is no retrieved company data to save.")
        return

    st.caption(
        f"Notes will be saved together with the briefing for {', '.join(briefing.successful_tickers)} "
        f"generated {format_timestamp(briefing.created_at)}."
    )
    key = briefing.briefing_id  # fresh, empty note fields for every new briefing
    with st.form(f"rm_note_form_{key}"):
        left, right = st.columns(2)
        client_reference = left.text_input(
            "Client or briefing reference *", placeholder="e.g. Acme Holdings – Q4 review", key=f"ref_{key}"
        )
        meeting_date = right.date_input("Meeting date", value=date.today(), key=f"meeting_{key}")
        discussion_summary = st.text_area(
            "Discussion summary *", placeholder="What was discussed with the client?", key=f"summary_{key}"
        )
        client_priorities = st.text_area("Client priorities or concerns", key=f"priorities_{key}")
        follow_up_actions = st.text_area("Follow-up actions", key=f"actions_{key}")
        next_review_date = st.date_input("Next review date (optional)", value=None, key=f"review_{key}")
        free_text = st.text_area("Other notes (optional)", key=f"other_{key}")
        submitted = st.form_submit_button("Save briefing and RM notes", type="primary")

    if not submitted:
        return
    if not client_reference.strip() or not discussion_summary.strip():
        st.error("Please enter a client or briefing reference and a discussion summary before saving.")
        return

    note = RmNote(
        client_reference=client_reference.strip(),
        meeting_date=meeting_date.isoformat() if meeting_date else None,
        discussion_summary=discussion_summary.strip(),
        client_priorities=client_priorities.strip(),
        follow_up_actions=follow_up_actions.strip(),
        next_review_date=next_review_date.isoformat() if next_review_date else None,
        free_text=free_text.strip(),
        created_at=utc_now_iso(),
    )
    try:
        result = briefing_store.save_briefing(briefing, note)
    except Exception as exc:
        st.error(f"The briefing could not be saved: {exc}")
        return
    st.session_state["saved"][briefing.briefing_id] = result.filename
    st.session_state["saved_note"] = result.briefing.note or note
    st.rerun()


def history_section() -> None:
    url = database_url()
    try:
        counts = database.count_rows()
    except Exception as exc:
        st.error(f"Cannot reach the briefing database ({describe_database_url(url)}): {exc}")
        return
    def plural(count: int, word: str) -> str:
        return f"{count} {word}{'' if count == 1 else 's'}"

    st.caption(
        f"Database: {describe_database_url(url)} · {plural(counts['briefings'], 'briefing')}, "
        f"{plural(counts['briefing_tickers'], 'ticker record')}, {plural(counts['rm_notes'], 'RM note')}."
    )

    with st.form("history_search_form"):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 2, 1])
        ticker = c1.text_input("Ticker", placeholder="e.g. MU")
        date_from = c2.date_input("Saved from", value=None)
        date_to = c3.date_input("Saved to", value=None)
        client_reference = c4.text_input("Client / briefing reference contains")
        analysis_type = c5.selectbox("Analysis type", ["All", ANALYSIS_TYPE])
        if st.form_submit_button("Search"):
            st.session_state["history_filters"] = {
                "ticker": ticker,
                "date_from": date_from,
                "date_to": date_to,
                "client_reference": client_reference,
                "analysis_type": None if analysis_type == "All" else analysis_type,
            }
            st.session_state["open_briefing_id"] = None

    try:
        results = database.search_briefings(**st.session_state["history_filters"])
    except Exception as exc:
        st.error(f"Search failed: {exc}")
        return
    if not results:
        st.info("No saved briefings match these filters.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Saved (UTC)": row["saved_at"].strftime("%Y-%m-%d %H:%M"),
                    "Companies": row["tickers"],
                    "Client / reference": row["client_reference"] or "",
                    "Type": row["analysis_type"],
                    "Price period": row["analysis_period"],
                    "File": row["filename"],
                }
                for row in results
            ]
        ),
        hide_index=True,
    )

    labels = {
        row["briefing_id"]: f"{row['saved_at'].strftime('%Y-%m-%d %H:%M')} · {row['tickers']} · "
        f"{row['client_reference'] or 'no reference'}"
        for row in results
    }
    chosen = st.selectbox("Choose a saved briefing", list(labels), format_func=labels.get)
    if st.button("Open briefing"):
        st.session_state["open_briefing_id"] = chosen

    open_id = st.session_state.get("open_briefing_id")
    if open_id:
        render_historical(open_id)


def render_historical(briefing_id: str) -> None:
    try:
        briefing, row = briefing_store.open_briefing(briefing_id)
    except Exception as exc:
        st.error(f"Could not open the saved briefing: {exc}")
        return
    st.divider()
    st.header(f"Saved briefing: {', '.join(briefing.successful_tickers)}")
    st.info(
        f"📁 **Historical snapshot.** Saved {format_timestamp(briefing.saved_at)}; data retrieved "
        f"{format_timestamp(briefing.created_at)}. These figures are exactly as saved; Nimbus has not "
        "retrieved current data."
    )
    try:
        st.download_button(
            "Download as Markdown",
            data=snapshots.read_markdown(row["filename"]),
            file_name=row["filename"],
            mime="text/markdown",
            key=f"download_{briefing_id}",
        )
    except (OSError, ValueError):
        st.caption("The Markdown file for this briefing is not available on this machine.")
    st.subheader("RM notes")
    render_note(briefing.note)
    st.subheader("Company comparison")
    render_comparison(briefing)
    st.subheader("Financial statements")
    render_financials(briefing)
    st.subheader("News and ratings")
    render_news_and_ratings(briefing)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def main() -> None:
    init_state()
    st.title("☁️ Nimbus")
    st.caption(
        "Company briefings for relationship managers: compare companies, review financials, news and "
        "analyst ratings, record meeting notes and reopen earlier briefings."
    )

    with st.sidebar:
        st.markdown("### About this briefing data")
        st.markdown(
            "- Market data, statements, ratings and news: **Yahoo Finance** (via yfinance)\n"
            f"- Retrieved data is reused for {CACHE_TTL_SECONDS // 60} minutes\n"
            "- Saved briefings are snapshots and are never refreshed"
        )
        st.caption(f"Nimbus {APP_VERSION}")

    st.markdown("#### New briefing")
    generate_section()

    briefing: Optional[Briefing] = st.session_state.get("briefing")
    if briefing is not None and briefing.companies:
        st.caption(
            f"Briefing for {', '.join(briefing.successful_tickers)} · generated "
            f"{format_timestamp(briefing.created_at)} · share-price period {briefing.analysis_period}"
        )

    tabs = st.tabs(["📊 Company comparison", "📑 Financials", "📰 News & ratings", "📝 RM notes & save",
                    "🗂️ Briefing history"])
    with tabs[0]:
        if briefing is None:
            st.info("Enter at least two tickers above and select **Generate briefing**.")
        else:
            render_comparison(briefing)
    with tabs[1]:
        if briefing is None:
            st.info("Generate a briefing to see financial statements.")
        else:
            render_financials(briefing)
    with tabs[2]:
        if briefing is None:
            st.info("Generate a briefing to see news and analyst ratings.")
        else:
            render_news_and_ratings(briefing)
    with tabs[3]:
        notes_and_save_section(briefing)
    with tabs[4]:
        history_section()


main()
