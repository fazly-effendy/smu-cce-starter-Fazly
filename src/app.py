"""Nimbus: company briefings for relationship managers.

Run with:  python3 -m streamlit run src/app.py

Workflow: generate a briefing for two or more companies -> compare them ->
read financials, news and ratings -> add RM notes -> save -> search history
-> reopen a saved briefing exactly as it was.

This file holds only the user interface. Data retrieval lives in services/,
calculations in analytics/, and saving/searching in storage/.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st

from analytics.formatting import (
    NOT_AVAILABLE,
    format_date,
    format_eps,
    format_money,
    format_multiple,
    format_percent,
    format_price,
    format_time_ago,
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
from services.company_lookup import (
    MAX_COMPANIES,
    CompanyMatch,
    is_list,
    resolve_company,
    resolve_entries,
    suggest_company,
)
from storage import briefing_store, database, snapshots

st.set_page_config(page_title="Nimbus · Company briefings", page_icon="☁️", layout="wide")

# Accent colour (same as primaryColor in .streamlit/config.toml) followed by
# distinct, colour-blind-friendly colours for further companies.
CHART_COLOURS = ["#2563EB", "#F59E0B", "#10B981", "#DB2777", "#7C3AED", "#0891B2"]
# Analyst rating buckets: green for buy, grey for hold, red for sell.
RATING_BUCKETS = [("strongBuy", "Strong buy", "#15803D"), ("buy", "Buy", "#4ADE80"), ("hold", "Hold", "#94A3B8"),
                  ("sell", "Sell", "#F87171"), ("strongSell", "Strong sell", "#B91C1C")]
CONSENSUS_BADGE = {"strong buy": "green", "buy": "green", "outperform": "green", "hold": "gray",
                   "underperform": "red", "sell": "red", "strong sell": "red"}
RESULT_BADGE = {"beat": "green", "miss": "red", "in line": "gray"}
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


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def cached_search(query: str) -> list:
    """Company-name search results, looked up at most once a day per query."""
    return yahoo.search_quotes(query)


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
    st.session_state.setdefault("saved", {})  # briefing_id -> saved filename
    st.session_state.setdefault("history_filters", {})
    st.session_state.setdefault("open_briefing_id", None)
    st.session_state.setdefault("period_label", DEFAULT_PERIOD_LABEL)
    # Company selection
    st.session_state.setdefault("selected_tickers", [])  # tickers shown as removable chips
    st.session_state.setdefault("companies", {})  # ticker -> CompanyMatch (name, exchange)
    st.session_state.setdefault("alternatives", {})  # ticker -> other matches the user can switch to
    st.session_state.setdefault("typed_as", {})  # ticker -> what the user typed, e.g. "Google"
    st.session_state.setdefault("lookup_feedback", {})  # suggestions / not found, for the last search
    st.session_state.setdefault("pinned_articles", {})  # briefing_id -> article keys to keep with the note


# --------------------------------------------------------------------------
# Company selection callbacks (run before the page redraws)
# --------------------------------------------------------------------------

def _search(query: str) -> list:
    return cached_search(query)


def add_company(match: CompanyMatch, typed: Optional[str] = None,
                alternatives: Optional[List[CompanyMatch]] = None) -> bool:
    """Add a company to the selection. Returns False if it is already there or the list is full."""
    selected = list(st.session_state["selected_tickers"])
    if match.ticker in selected or len(selected) >= MAX_COMPANIES:
        return False
    st.session_state["selected_tickers"] = selected + [match.ticker]
    st.session_state["companies"][match.ticker] = match
    if typed and typed.strip().upper() != match.ticker:
        st.session_state["typed_as"][match.ticker] = typed.strip()
    if alternatives:
        st.session_state["alternatives"][match.ticker] = list(alternatives)
    return True


def on_company_query() -> None:
    """Runs when the user presses Enter in the search box."""
    text = st.session_state.get("company_query", "").strip()
    feedback: Dict[str, object] = {"query": text, "suggestions": [], "not_found": [], "over_limit": []}
    if not text:
        st.session_state["lookup_feedback"] = {}
        return
    if len(st.session_state["selected_tickers"]) >= MAX_COMPANIES:
        feedback["over_limit"] = [text]
        st.session_state["lookup_feedback"] = feedback
        return

    matches = [] if is_list(text) else resolve_company(text, _search)
    if is_list(text) or (not matches and " " in text):
        resolution = resolve_entries(text, _search, already=st.session_state["selected_tickers"],
                                     limit=MAX_COMPANIES)
        for match in resolution.chosen:
            add_company(match, resolution.typed_as.get(match.ticker), resolution.alternatives.get(match.ticker))
        feedback["not_found"] = resolution.not_found
        feedback["over_limit"] = resolution.over_limit
        st.session_state["company_query"] = ""
    elif not matches:
        feedback["not_found"] = [(text, suggest_company(text))]
    elif matches[0].source == "alias" or matches[0].ticker == text.upper() or len(matches) == 1:
        if not add_company(matches[0], text, matches[1:]) and matches[0].ticker not in st.session_state["selected_tickers"]:
            feedback["over_limit"] = [matches[0].ticker]
        st.session_state["company_query"] = ""
    else:
        feedback["suggestions"] = matches  # several plausible companies: let the user pick
    st.session_state["lookup_feedback"] = feedback


def pick_suggestion(match: CompanyMatch, typed: str, others: List[CompanyMatch]) -> None:
    add_company(match, typed, [o for o in others if o.ticker != match.ticker])
    st.session_state["company_query"] = ""
    st.session_state["lookup_feedback"] = {}


def quick_add(ticker: str) -> None:
    matches = resolve_company(ticker, _search)
    best = next((m for m in matches if m.ticker == ticker), None) or CompanyMatch(ticker, ticker, None, "typed")
    add_company(best)


def switch_listing(old_ticker: str) -> None:
    """Replace a chosen company with one of its alternative matches (e.g. GOOGL -> GOOG)."""
    new_ticker = st.session_state.get(f"switch_{old_ticker}")
    alternatives = st.session_state["alternatives"].get(old_ticker, [])
    new = next((m for m in alternatives if m.ticker == new_ticker), None)
    if new is None or new_ticker in st.session_state["selected_tickers"]:
        return
    old = st.session_state["companies"].get(old_ticker)
    selected = list(st.session_state["selected_tickers"])
    selected[selected.index(old_ticker)] = new.ticker
    st.session_state["selected_tickers"] = selected
    st.session_state["companies"][new.ticker] = new
    st.session_state["alternatives"][new.ticker] = ([old] if old else []) + [m for m in alternatives if m.ticker != new.ticker]
    if old_ticker in st.session_state["typed_as"]:
        st.session_state["typed_as"][new.ticker] = st.session_state["typed_as"].pop(old_ticker)


def open_from_sidebar(briefing_id: str) -> None:
    st.session_state["history_filters"] = {}
    st.session_state["open_briefing_id"] = briefing_id
    st.session_state["sidebar_opened"] = True


# --------------------------------------------------------------------------
# Rendering: used for both the live briefing and reopened historical ones
# --------------------------------------------------------------------------

def render_notices(briefing: Briefing) -> None:
    """One compact, collapsible notice listing companies that could not be retrieved."""
    problems: List[str] = []
    for ticker, reason in briefing.failed_tickers.items():
        suggestion = suggest_company(ticker)
        hint = f" Did you mean **{md_text(suggestion.name)} ({suggestion.ticker})**?" if (
            suggestion and suggestion.ticker != ticker) else ""
        detail = "Yahoo Finance has no price data for this symbol." if "No price data" in reason else md_text(reason)
        problems.append(f"**{ticker}**: {detail}{hint}")
    if problems:
        label = f"⚠️ {len(problems)} {'company was' if len(problems) == 1 else 'companies were'} not included. Details"
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
    else:
        st.altair_chart(chart)
        if briefing.price_window:
            st.caption(
                f"Adjusted closing prices from {format_date(briefing.price_window[0])} to "
                f"{format_date(briefing.price_window[1])}, on dates when every company traded. Each line starts "
                "at 100 (dashed line); hover for the date and actual price."
            )

    render_analyst_view(briefing)
    render_earnings(briefing)


def ratings_chart(briefing: Briefing) -> Optional[alt.Chart]:
    """Share of analysts per recommendation, one bar per company."""
    rows = []
    for company in briefing.companies:
        for order, (key, label, _) in enumerate(RATING_BUCKETS):
            count = (company.ratings or {}).get(key)
            if count:
                rows.append({"Company": company.ticker, "Rating": label, "Analysts": count, "Order": order})
    if not rows:
        return None
    tickers = [c.ticker for c in briefing.companies if c.ratings]
    return alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
        y=alt.Y("Company:N", title=None, sort=tickers),
        x=alt.X("Analysts:Q", stack="normalize", title="Share of analysts (current month)",
                axis=alt.Axis(format="%")),
        color=alt.Color("Rating:N", legend=alt.Legend(orient="top", title=None),
                        scale=alt.Scale(domain=[b[1] for b in RATING_BUCKETS], range=[b[2] for b in RATING_BUCKETS])),
        order=alt.Order("Order:Q"),
        tooltip=["Company:N", "Rating:N", "Analysts:Q"],
    ).properties(height=36 * len(tickers) + 50, width="container")


def render_analyst_view(briefing: Briefing) -> None:
    st.markdown("#### Analyst view")
    chart = ratings_chart(briefing)
    if chart is not None:
        st.altair_chart(chart)
    rows = []
    for company in briefing.companies:
        view = company.analyst or {}
        consensus = view.get("recommendation")
        target_range = (f"{format_price(view.get('target_low'), company.currency)} – "
                        f"{format_price(view.get('target_high'), company.currency)}"
                        if view.get("target_low") is not None and view.get("target_high") is not None else NOT_AVAILABLE)
        rows.append(
            f"| {company.ticker} | "
            + (badge(consensus.title(), CONSENSUS_BADGE.get(consensus, "gray")) if consensus else NOT_AVAILABLE)
            + f" | {view.get('analysts') or NOT_AVAILABLE} | {format_price(view.get('target_mean'), company.currency)}"
            f" | {format_percent(view.get('upside'))} | {target_range} |"
        )
    st.markdown(
        "| Company | Consensus | Analysts | Mean price target | Upside to target | Target range |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows)
    )
    st.caption("Analyst consensus and price targets from Yahoo Finance at retrieval time. Upside = mean target ÷ "
               "last close − 1. These are third-party analyst views, not Nimbus recommendations.")


def render_earnings(briefing: Briefing) -> None:
    st.markdown("#### Earnings")
    rows = []
    for company in briefing.companies:
        e = company.earnings or {}
        result = e.get("last_result")
        outcome = NOT_AVAILABLE
        if result:
            surprise = e.get("last_surprise")
            outcome = badge(result.title(), RESULT_BADGE.get(result, "gray")) + (
                f" {format_percent(surprise)}" if surprise is not None else "")
        rows.append(
            f"| {company.ticker} | {format_date(e.get('next_date'))} | {format_eps(e.get('next_eps_estimate'))} | "
            f"{format_date(e.get('last_date'))} | {format_eps(e.get('last_eps_actual'))} vs "
            f"{format_eps(e.get('last_eps_estimate'))} | {outcome} |"
        )
    st.markdown(
        "| Company | Next earnings | EPS estimate (next) | Last reported | EPS actual vs estimate | Result |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows)
    )
    st.caption("From Yahoo Finance at retrieval time; scheduled dates can change. Result compares reported EPS with "
               "the analyst estimate: surprise = (actual − estimate) ÷ |estimate|.")


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


def article_key(item) -> str:
    return hashlib.md5(f"{item.ticker}|{item.source_url or item.headline}".encode("utf-8")).hexdigest()[:12]


def toggle_saved_article(briefing_id: str, key: str) -> None:
    pinned = list(st.session_state["pinned_articles"].get(briefing_id, []))
    if key in pinned:
        pinned.remove(key)
    else:
        pinned.append(key)
    st.session_state["pinned_articles"][briefing_id] = pinned


def render_news_feed(briefing: Briefing, live: bool) -> None:
    """All companies' news as one feed of cards, newest first, with a company filter.

    live=True for the briefing being prepared (relative times, Save to note);
    live=False for a reopened snapshot (fixed dates, read-only).
    """
    if not briefing.companies:
        st.info("No company data to show.")
        return
    prefix = "live" if live else f"hist_{briefing.briefing_id[:8]}"
    chosen = st.segmented_control(
        "Show news for", briefing.successful_tickers, selection_mode="multi",
        default=briefing.successful_tickers, key=f"{prefix}_news_filter",
        help="Click a company to hide or show its news. With none selected, all news is shown.",
    )
    items = [item for company in briefing.companies for item in company.news]
    if chosen:
        items = [item for item in items if item.ticker in chosen]
    items.sort(key=lambda item: item.published_at or "", reverse=True)

    saved = briefing.briefing_id in st.session_state["saved"]
    pinned = st.session_state["pinned_articles"].get(briefing.briefing_id, [])
    can_pin = live and not saved
    st.caption(
        f"{len(items)} {'article' if len(items) == 1 else 'articles'}, newest first."
        + (" Use **Save to note** to keep an article with your RM note." if can_pin else "")
    )
    if not items:
        st.info("No recent news available from Yahoo Finance.")

    for item in items:
        with st.container(border=True):
            if item.thumbnail_url:
                picture, text = st.columns([1, 7])
                picture.image(item.thumbnail_url, width=110)
            else:
                text = st.container()
            headline = md_text(item.headline)
            text.markdown(f"**[{headline}]({item.source_url})**" if item.source_url else f"**{headline}**")
            when = (format_time_ago(item.published_at) if live else format_date(item.published_at)) \
                if item.published_at else "date not provided"
            text.markdown(" · ".join([badge(item.ticker), md_text(item.publisher) or "Publisher not provided", when]))
            text.markdown(md_text(item.summary) if item.summary else "_No summary provided by the source._")
            if can_pin:
                key = article_key(item)
                text.button("★ Saved to note" if key in pinned else "☆ Save to note", key=f"pin_{key}",
                            on_click=toggle_saved_article, args=(briefing.briefing_id, key))

    notes = [f"{company.ticker}: {md_text(w)}" for company in briefing.companies for w in company.warnings]
    if notes:
        st.caption("Notes: " + " · ".join(notes))


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
        if note.saved_articles:
            st.markdown("**Saved articles**")
            st.markdown(render_article_list(note.saved_articles))


def render_article_list(articles) -> str:
    lines = []
    for article in articles:
        headline = md_text(article.get("headline"))
        title = f"[{headline}]({article['source_url']})" if article.get("source_url") else headline
        meta = " · ".join(x for x in [article.get("ticker"), md_text(article.get("publisher")),
                                       format_date(article.get("published_at")) if article.get("published_at") else ""] if x)
        lines.append(f"- {title} ({meta})")
    return "\n".join(lines)


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
            columns[index % 2].button(ticker, key=f"quick_{ticker}", on_click=quick_add, args=(ticker,))

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


def company_picker() -> None:
    """Search box, removable chips and a confirmation row of the chosen companies."""
    st.text_input(
        "Find companies",
        key="company_query",
        on_change=on_company_query,
        placeholder="Type a name or ticker and press Enter, e.g. nvidia, Google, MU, or a list: AAPL, MSFT, DBS",
        help="Company names and tickers both work. Separate several with commas. "
             f"Up to {MAX_COMPANIES} companies per briefing.",
    )

    feedback = st.session_state.get("lookup_feedback") or {}
    suggestions = feedback.get("suggestions") or []
    if suggestions:
        st.caption(f"Matches for “{md_text(feedback['query'])}”. Choose one to add:")
        for index, match in enumerate(suggestions):
            left, right = st.columns([6, 1], vertical_alignment="center")
            left.markdown(f"{md_text(match.name)} &nbsp; {badge(match.ticker)}"
                          + (f" &nbsp; · {md_text(match.exchange)}" if match.exchange else ""))
            right.button("Add", key=f"pick_{index}_{match.ticker}", on_click=pick_suggestion,
                         args=(match, feedback["query"], suggestions))
    for typed, suggestion in feedback.get("not_found") or []:
        message = f"No company found for “{md_text(typed)}”."
        if suggestion:
            left, right = st.columns([6, 1], vertical_alignment="center")
            left.warning(f"{message} Did you mean {md_text(suggestion.name)} ({suggestion.ticker})?")
            right.button(f"Add {suggestion.ticker}", key=f"didyoumean_{suggestion.ticker}",
                         on_click=pick_suggestion, args=(suggestion, typed, []))
        else:
            st.warning(f"{message} Check the spelling or enter the ticker symbol.")
    if feedback.get("over_limit"):
        st.caption(f"A briefing compares up to {MAX_COMPANIES} companies. Remove one to add "
                   + ", ".join(md_text(t) for t in feedback["over_limit"]) + ".")

    selected = st.session_state["selected_tickers"]
    companies: Dict[str, CompanyMatch] = st.session_state["companies"]
    # Options are every company found this session, not just the current selection. Keeping the list
    # stable matters: older Streamlit versions (1.50, used on EC2) reset a multiselect whose options
    # change, which would clear all chips when one is removed. It also lets users re-add a removed one.
    known = list(dict.fromkeys(list(companies) + list(selected)))
    st.multiselect(
        "Companies in this briefing",
        options=known,
        key="selected_tickers",
        format_func=lambda t: f"{t} · {companies[t].name}" if t in companies and companies[t].name != t else t,
        placeholder="No companies yet: search above or use Quick add in the sidebar",
        help="Click × on a company to remove it.",
    )

    if selected:
        st.caption("Check the companies before generating:")
        for ticker in selected:
            match = companies.get(ticker, CompanyMatch(ticker, ticker, None, "typed"))
            typed = st.session_state["typed_as"].get(ticker)
            alternatives = st.session_state["alternatives"].get(ticker, [])
            c1, c2, c3, c4 = st.columns([4, 1.4, 1.6, 3], vertical_alignment="center")
            c1.markdown(f"**{md_text(match.name)}**" + (f"  \n_typed “{md_text(typed)}”_" if typed else ""))
            c2.markdown(badge(ticker))
            c3.caption(match.exchange or ("Checked on generate" if match.source == "typed" else "Exchange n/a"))
            if alternatives:
                options = [ticker] + [m.ticker for m in alternatives]
                labels = {ticker: f"Keep {ticker}"}
                labels.update({m.ticker: f"Switch to {m.label}" for m in alternatives})
                c4.selectbox("Other matches", options, key=f"switch_{ticker}", format_func=labels.get,
                             on_change=switch_listing, args=(ticker,), label_visibility="collapsed")


def generate_section() -> None:
    with st.container(border=True):
        st.markdown("**New briefing**")
        company_picker()
        left, right = st.columns([2, 5], vertical_alignment="bottom")
        period_label = left.selectbox("Share-price period", list(ANALYSIS_PERIODS), key="period_label")
        clicked = right.button("Generate briefing", type="primary")

    if not clicked:
        return
    tickers = list(st.session_state["selected_tickers"])
    if len(tickers) < 2:
        st.error("Add at least two companies to generate a comparison briefing.")
        return
    with st.spinner(f"Retrieving {', '.join(tickers)} from Yahoo Finance…"):
        briefing = build_briefing(
            tickers,
            period_label,
            ANALYSIS_PERIODS[period_label],
            fetch_history=cached_price_history,
            fetch_company=cached_company_data,
        )
    st.session_state["briefing"] = briefing
    if not briefing.companies:
        st.error("None of the companies could be retrieved. Check the symbols and try again.")


def pinned_articles(briefing: Briefing) -> List[Dict[str, Optional[str]]]:
    """The articles the RM marked with Save to note, in the order they were saved."""
    by_key = {article_key(item): item for company in briefing.companies for item in company.news}
    return [
        {"ticker": item.ticker, "headline": item.headline, "publisher": item.publisher,
         "published_at": item.published_at, "source_url": item.source_url}
        for item in (by_key.get(key) for key in st.session_state["pinned_articles"].get(briefing.briefing_id, []))
        if item is not None
    ]


def save_from_form(briefing: Briefing) -> None:
    """'Save briefing and RM notes' click handler.

    Runs before the page is redrawn, so the whole page (including the News tab's
    Save to note buttons) is drawn once, already in its saved state. This avoids
    relying on st.rerun(), which older Streamlit versions do not always honour.
    """
    key = briefing.briefing_id
    state = st.session_state
    client_reference = (state.get(f"ref_{key}") or "").strip()
    discussion_summary = (state.get(f"summary_{key}") or "").strip()
    if not client_reference or not discussion_summary:
        state["save_error"] = "Please enter a client or briefing reference and a discussion summary before saving."
        return
    meeting_date = state.get(f"meeting_{key}")
    next_review_date = state.get(f"review_{key}")
    note = RmNote(
        client_reference=client_reference,
        meeting_date=meeting_date.isoformat() if meeting_date else None,
        discussion_summary=discussion_summary,
        client_priorities=(state.get(f"priorities_{key}") or "").strip(),
        follow_up_actions=(state.get(f"actions_{key}") or "").strip(),
        next_review_date=next_review_date.isoformat() if next_review_date else None,
        free_text=(state.get(f"other_{key}") or "").strip(),
        created_at=utc_now_iso(),
        saved_articles=pinned_articles(briefing),
    )
    try:
        result = briefing_store.save_briefing(briefing, note)
    except Exception as exc:
        state["save_error"] = f"The briefing could not be saved: {exc}"
        return
    state["saved"][key] = result.filename
    state["saved_note"] = result.briefing.note or note
    state.pop("save_error", None)


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
    articles = pinned_articles(briefing)
    if articles:
        st.markdown(f"**Articles to keep with this note ({len(articles)})**")
        st.markdown(render_article_list(articles))
    else:
        st.caption("Tip: use **Save to note** in the News tab to keep relevant articles with this note.")

    key = briefing.briefing_id  # fresh, empty note fields for every new briefing
    with st.form(f"rm_note_form_{key}"):
        left, right = st.columns(2)
        left.text_input("Client or briefing reference *", placeholder="e.g. Acme Holdings – Q4 review",
                        key=f"ref_{key}")
        right.date_input("Meeting date", value=date.today(), key=f"meeting_{key}")
        st.text_area("Discussion summary *", placeholder="What was discussed with the client?", key=f"summary_{key}")
        left, right = st.columns(2)
        left.text_area("Client priorities or concerns", key=f"priorities_{key}")
        right.text_area("Follow-up actions", key=f"actions_{key}")
        left, right = st.columns([1, 3])
        left.date_input("Next review date (optional)", value=None, key=f"review_{key}")
        right.text_area("Other notes (optional)", key=f"other_{key}", height=68)
        st.form_submit_button("Save briefing and RM notes", type="primary", on_click=save_from_form,
                              args=(briefing,))

    error = st.session_state.pop("save_error", None)
    if error:
        st.error(error)


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
    render_notices(briefing)
    st.markdown("#### RM notes")
    render_note(briefing.note)
    st.markdown("#### Company comparison")
    render_comparison(briefing)
    st.markdown("#### Financial statements")
    render_financials(briefing)
    st.markdown("#### News")
    render_news_feed(briefing, live=False)


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
        render_notices(briefing)
        if briefing.companies:
            st.caption(
                f"Briefing for {', '.join(briefing.successful_tickers)} · generated "
                f"{format_timestamp(briefing.created_at)} · share-price period {briefing.analysis_period}"
            )

    if st.session_state.pop("sidebar_opened", False):
        st.toast("Saved briefing opened in the History tab.", icon="📁")

    tabs = st.tabs(["📊 Compare", "📑 Financials", "📰 News", "📝 Notes & save", "🗂️ History"])
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
            st.info("Generate a briefing to see the latest news for its companies.")
        else:
            render_news_feed(briefing, live=True)
    with tabs[3]:
        notes_and_save_section(briefing)
    with tabs[4]:
        history_section()


main()
