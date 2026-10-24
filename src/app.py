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
from typing import Dict, List, Optional

import altair as alt
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
from services.ticker_input import MAX_TICKERS, ParsedInput, parse_ticker_input, suggest_ticker
from storage import briefing_store, database, snapshots

st.set_page_config(page_title="Nimbus · Company briefings", page_icon="☁️", layout="wide")

# Accent colour (same as primaryColor in .streamlit/config.toml) followed by
# distinct, colour-blind-friendly colours for further companies.
CHART_COLOURS = ["#2563EB", "#F59E0B", "#10B981", "#DB2777", "#7C3AED", "#0891B2"]
POPULAR_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "MU", "JPM", "D05.SI", "O39.SI"]

_PAGE_CSS = """
<style>
/* Tighter top spacing so the briefing starts higher on the page */
.block-container {padding-top: 2rem; padding-bottom: 3rem;}
/* Slightly smaller metric values so four fit comfortably in a card */
div[data-testid="stMetricValue"] {font-size: 1.6rem;}
</style>
"""


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


def badge(text: str, colour: str = "blue") -> str:
    safe = text.replace("[", "(").replace("]", ")").replace("$", "\\$")
    return f":{colour}-badge[{safe}]"


def init_state() -> None:
    st.session_state.setdefault("briefing", None)  # the briefing currently on screen
    st.session_state.setdefault("input_notes", None)  # how the ticker input was interpreted
    st.session_state.setdefault("saved", {})  # briefing_id -> saved filename
    st.session_state.setdefault("history_filters", {})
    st.session_state.setdefault("open_briefing_id", None)
    st.session_state.setdefault("ticker_text", "AAPL, MSFT")
    st.session_state.setdefault("period_label", DEFAULT_PERIOD_LABEL)


def add_ticker(ticker: str) -> None:
    """Quick-add button callback: append a ticker to the input if not already there."""
    current = st.session_state.get("ticker_text", "")
    if ticker in parse_ticker_input(current, max_tickers=100).tickers:
        return
    st.session_state["ticker_text"] = f"{current.rstrip(', ')}, {ticker}" if current.strip() else ticker


def open_from_sidebar(briefing_id: str) -> None:
    st.session_state["history_filters"] = {}
    st.session_state["open_briefing_id"] = briefing_id
    st.session_state["sidebar_opened"] = True


# --------------------------------------------------------------------------
# Rendering: used for both the live briefing and reopened historical ones
# --------------------------------------------------------------------------

def render_notices(briefing: Briefing, notes: Optional[ParsedInput]) -> None:
    """One compact, collapsible notice instead of a stack of alert boxes."""
    if notes and notes.mapped:
        st.caption("Interpreted as: " + " · ".join(f"{md_text(typed)} → **{t}**" for typed, t in notes.mapped))

    problems: List[str] = []
    for entry in (notes.rejected if notes else []):
        hint = suggest_ticker(entry)
        problems.append(
            f"**{md_text(entry)}** is not a ticker symbol or a company name Nimbus recognises."
            + (f" Did you mean **{', '.join(hint)}**?" if hint else "")
        )
    for ticker, reason in briefing.failed_tickers.items():
        hint = [s for s in suggest_ticker(ticker) if s != ticker]
        detail = "Yahoo Finance has no price data for this symbol." if "No price data" in reason else md_text(reason)
        problems.append(f"**{ticker}**: {detail}" + (f" Did you mean **{', '.join(hint)}**?" if hint else ""))
    for ticker in (notes.truncated if notes else []):
        problems.append(f"**{ticker}** was left out: a briefing compares up to {MAX_TICKERS} companies.")

    if problems:
        label = f"⚠️ {len(problems)} {'entry was' if len(problems) == 1 else 'entries were'} not included. Details"
        with st.expander(label, expanded=False):
            st.markdown("\n".join(f"- {p}" for p in problems))


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


def render_company_cards(briefing: Briefing) -> None:
    companies = briefing.companies
    per_row = min(len(companies), 3)
    for start in range(0, len(companies), per_row):
        columns = st.columns(per_row)
        for column, company in zip(columns, companies[start:start + per_row]):
            with column.container(border=True):
                st.markdown(f"**{md_text(company.name)}** &nbsp; {badge(company.ticker)}")
                hpr = briefing.holding_period_returns.get(company.ticker)
                left, middle, right = st.columns(3)
                left.metric(
                    "Last close",
                    format_price(company.last_close, company.currency),
                    delta=f"{format_percent(hpr)} · {briefing.analysis_period}" if hpr is not None else None,
                    help=f"Adjusted close on {format_date(company.last_close_date)}. "
                         "The coloured figure is the holding-period return.",
                )
                middle.metric("Market cap", format_money(company.market_cap, company.currency))
                right.metric("P/E (trailing)", format_multiple(company.pe_ratio))


def price_chart(briefing: Briefing) -> Optional[alt.LayerChart]:
    """Rebased share prices with a 100 baseline, a legend and hover tooltips."""
    currencies = {c.ticker: c.currency for c in briefing.companies}
    rows = []
    for ticker, series in briefing.price_index.items():
        prices = briefing.price_history.get(ticker, {})
        for day, rebased in series.items():
            rows.append({
                "Date": day,
                "Company": ticker,
                "Rebased": rebased,
                "Close": format_price(prices.get(day), currencies.get(ticker)) if prices else NOT_AVAILABLE,
            })
    if not rows:
        return None
    data = pd.DataFrame(rows)
    data["Date"] = pd.to_datetime(data["Date"])
    tickers = list(briefing.price_index)

    low = min(data["Rebased"].min(), 100.0)
    high = max(data["Rebased"].max(), 100.0)
    pad = max((high - low) * 0.08, 2.0)

    base = alt.Chart(data).encode(
        x=alt.X("Date:T", title=None, scale=alt.Scale(nice=False), axis=alt.Axis(format="%b %Y", tickCount=6)),
        y=alt.Y("Rebased:Q", title="Rebased price (start = 100)",
                scale=alt.Scale(domain=[low - pad, high + pad], zero=False, nice=False)),
        color=alt.Color("Company:N", scale=alt.Scale(domain=tickers, range=CHART_COLOURS[:len(tickers)]),
                        legend=alt.Legend(orient="top", title=None)),
    )
    hover = alt.selection_point(fields=["Date"], nearest=True, on="mouseover", empty=False, clear="mouseout")
    lines = base.mark_line(strokeWidth=2.2)
    points = base.mark_circle(size=70).encode(
        opacity=alt.condition(hover, alt.value(1.0), alt.value(0.0)),
        tooltip=[
            alt.Tooltip("Date:T", format="%d %b %Y"),
            alt.Tooltip("Company:N"),
            alt.Tooltip("Rebased:Q", format=".1f", title="Rebased"),
            alt.Tooltip("Close:N", title="Adjusted close"),
        ],
    ).add_params(hover)
    cursor = alt.Chart(data).mark_rule(color="#94A3B8", strokeWidth=1).encode(x="Date:T").transform_filter(hover)
    baseline = alt.Chart(pd.DataFrame({"Rebased": [100.0]})).mark_rule(
        strokeDash=[6, 4], color="#94A3B8", strokeWidth=1.5
    ).encode(y="Rebased:Q")
    return alt.layer(baseline, lines, cursor, points).properties(height=380, width="container")


def render_comparison(briefing: Briefing) -> None:
    companies = briefing.companies
    if not companies:
        st.info("No company data to show.")
        return

    render_company_cards(briefing)
    if len(companies) < 2:
        with st.container(border=True):
            st.markdown("**Add another ticker to compare.**")
            st.caption(
                "Only one company was retrieved, so the measures below have nothing to be compared with. "
                "Add a second company in the box above, or use Quick add in the sidebar, then generate again."
            )

    st.markdown("#### Financial comparison")
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
            "- Companies can have different fiscal year-ends; the last row shows which year each uses."
        )

    st.markdown("#### Share-price performance")
    chart = price_chart(briefing)
    if chart is None:
        st.info("Not enough common trading days to draw a comparison chart.")
        return
    st.altair_chart(chart)
    if briefing.price_window:
        st.caption(
            f"Adjusted closing prices from {format_date(briefing.price_window[0])} to "
            f"{format_date(briefing.price_window[1])}, on dates when every company traded. Each line starts at 100 "
            "(dashed line); hover for the date and actual price."
        )


def render_financials(briefing: Briefing) -> None:
    if not briefing.companies:
        st.info("No company data to show.")
        return
    for company in briefing.companies:
        with st.container(border=True):
            st.markdown(f"**{md_text(company.name)}** &nbsp; {badge(company.ticker)}")
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
        with st.container(border=True):
            st.markdown(f"**{md_text(company.name)}** &nbsp; {badge(company.ticker)}")
            ratings = company.ratings
            if ratings:
                labels = [("strongBuy", "Strong buy"), ("buy", "Buy"), ("hold", "Hold"), ("sell", "Sell"),
                          ("strongSell", "Strong sell")]
                counts = [ratings.get(key) for key, _ in labels]
                st.caption("Analyst recommendations (number of analysts, current month)")
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
                    part for part in [md_text(item.publisher),
                                      format_date(item.published_at) if item.published_at else ""]
                    if part
                )
                st.markdown(f"**{title}**  \n{meta or 'Publisher and date not provided'}")
                st.markdown(md_text(item.summary) if item.summary else "_No summary provided by the source._")
                if not item.source_url:
                    st.caption("Source link not provided by Yahoo.")
            for warning in company.warnings:
                st.caption(f"Note: {md_text(warning)}")


def render_note(note: Optional[RmNote]) -> None:
    if not note:
        st.info("No RM note was saved with this briefing.")
        return
    with st.container(border=True):
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

def sidebar() -> None:
    with st.sidebar:
        st.markdown("### ☁️ Nimbus")
        st.caption("Company briefings for relationship managers")

        st.markdown("**Quick add**")
        columns = st.columns(2)
        for index, ticker in enumerate(POPULAR_TICKERS):
            columns[index % 2].button(ticker, key=f"quick_{ticker}", on_click=add_ticker, args=(ticker,))

        st.markdown("**Recent briefings**")
        try:
            recent = database.search_briefings(limit=5)
            if not recent:
                st.caption("Saved briefings will appear here.")
        except Exception:
            recent = []
            st.caption("Saved briefings are unavailable (database not reachable).")
        for row in recent:
            label = f"{row['tickers']} · {row['saved_at'].strftime('%d %b %H:%M')}"
            st.button(label, key=f"recent_{row['briefing_id']}", on_click=open_from_sidebar,
                      args=(row["briefing_id"],), help=row["client_reference"] or None)

        with st.expander("About the data"):
            st.markdown(
                "- Market data, statements, ratings and news: **Yahoo Finance** (via yfinance)\n"
                f"- Retrieved data is reused for {CACHE_TTL_SECONDS // 60} minutes\n"
                "- Saved briefings are snapshots and are never refreshed\n"
                "- Figures are historical, not forecasts or advice"
            )
        st.caption(f"Nimbus {APP_VERSION}")


def generate_section() -> None:
    with st.container(border=True):
        st.markdown("**New briefing**")
        left, middle, right = st.columns([5, 2, 2], vertical_alignment="bottom")
        text = left.text_input(
            "Companies: tickers or company names",
            key="ticker_text",
            placeholder="e.g. Apple, Microsoft or AAPL, MSFT",
            help="Separate companies with commas, spaces or semicolons. Common company names are converted to "
                 f"tickers. Up to {MAX_TICKERS} companies. Press Enter to preview.",
        )
        period_label = middle.selectbox("Share-price period", list(ANALYSIS_PERIODS), key="period_label")
        clicked = right.button("Generate briefing", type="primary")

        parsed = parse_ticker_input(text)
        if parsed.tickers:
            preview = " ".join(badge(t) for t in parsed.tickers)
            preview += "".join(" " + badge(f"{t}: over limit", "gray") for t in parsed.truncated)
            preview += "".join(" " + badge(f"{e}: not recognised", "red") for e in parsed.rejected)
            st.markdown(f"Will compare: {preview}")
        elif text.strip():
            st.caption("No ticker symbols or known company names found yet.")

    if not clicked:
        return
    if len(parsed.tickers) < 2:
        st.error("Enter at least two different companies to generate a comparison briefing.")
        return
    with st.spinner(f"Retrieving {', '.join(parsed.tickers)} from Yahoo Finance…"):
        briefing = build_briefing(
            parsed.tickers,
            period_label,
            ANALYSIS_PERIODS[period_label],
            fetch_history=cached_price_history,
            fetch_company=cached_company_data,
        )
    st.session_state["briefing"] = briefing
    st.session_state["input_notes"] = parsed
    if not briefing.companies:
        st.error("None of the companies could be retrieved. Check the symbols and try again.")


def notes_and_save_section(briefing: Optional[Briefing]) -> None:
    if briefing is None:
        st.info("Generate a briefing first, then record your meeting notes here.")
        return
    saved_filename = st.session_state["saved"].get(briefing.briefing_id)
    if saved_filename:
        st.success(f"This briefing and its RM note were saved as **{saved_filename}**.")
        st.caption("Find it under History or Recent briefings in the sidebar. Generate a new briefing to start another.")
        render_note(st.session_state.get("saved_note"))
        return
    if not briefing.companies:
        st.warning("There is no retrieved company data to save.")
        return

    st.caption(
        f"Notes will be saved together with the briefing for {', '.join(briefing.successful_tickers)} "
        f"generated {format_timestamp(briefing.created_at)}. Fields marked * are required."
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
        left, right = st.columns(2)
        client_priorities = left.text_area("Client priorities or concerns", key=f"priorities_{key}")
        follow_up_actions = right.text_area("Follow-up actions", key=f"actions_{key}")
        left, right = st.columns([1, 3])
        next_review_date = left.date_input("Next review date (optional)", value=None, key=f"review_{key}")
        free_text = right.text_area("Other notes (optional)", key=f"other_{key}", height=68)
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

    open_id = st.session_state.get("open_briefing_id")
    if not results and not open_id:
        st.info("No saved briefings match these filters.")
        return

    if results:
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
        left, right = st.columns([4, 1], vertical_alignment="bottom")
        chosen = left.selectbox("Choose a saved briefing", list(labels), format_func=labels.get)
        if right.button("Open briefing"):
            st.session_state["open_briefing_id"] = chosen
            open_id = chosen

    if open_id:
        render_historical(open_id)


def render_historical(briefing_id: str) -> None:
    try:
        briefing, row = briefing_store.open_briefing(briefing_id)
    except Exception as exc:
        st.error(f"Could not open the saved briefing: {exc}")
        return
    st.divider()
    left, right = st.columns([4, 1], vertical_alignment="bottom")
    left.markdown(f"### Saved briefing: {', '.join(briefing.successful_tickers)}")
    try:
        right.download_button(
            "Download as Markdown",
            data=snapshots.read_markdown(row["filename"]),
            file_name=row["filename"],
            mime="text/markdown",
            key=f"download_{briefing_id}",
        )
    except (OSError, ValueError):
        right.caption("Markdown file not available on this machine.")
    st.info(
        f"📁 **Historical snapshot.** Saved {format_timestamp(briefing.saved_at)}; data retrieved "
        f"{format_timestamp(briefing.created_at)}. These figures are exactly as saved; Nimbus has not "
        "retrieved current data."
    )
    render_notices(briefing, None)
    st.markdown("#### RM notes")
    render_note(briefing.note)
    st.markdown("#### Company comparison")
    render_comparison(briefing)
    st.markdown("#### Financial statements")
    render_financials(briefing)
    st.markdown("#### News and ratings")
    render_news_and_ratings(briefing)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def main() -> None:
    init_state()
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    sidebar()

    st.title("☁️ Nimbus")
    st.caption(
        "Compare companies, review financials, news and analyst ratings, record meeting notes and reopen "
        "earlier briefings."
    )
    generate_section()

    briefing: Optional[Briefing] = st.session_state.get("briefing")
    if briefing is not None:
        render_notices(briefing, st.session_state.get("input_notes"))
        if briefing.companies:
            st.caption(
                f"Briefing for {', '.join(briefing.successful_tickers)} · generated "
                f"{format_timestamp(briefing.created_at)} · share-price period {briefing.analysis_period}"
            )

    if st.session_state.pop("sidebar_opened", False):
        st.toast("Saved briefing opened in the History tab.", icon="📁")

    tabs = st.tabs(["📊 Compare", "📑 Financials", "📰 News & ratings", "📝 Notes & save", "🗂️ History"])
    with tabs[0]:
        if briefing is None:
            st.info("Enter at least two companies above and select **Generate briefing**.")
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
