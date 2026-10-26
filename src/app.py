"""Nimbus: client discussions for relationship managers.

Run with:  python3 -m streamlit run src/app.py

Workflow (the instructor's acceptance test): choose or enter a Client ID ->
add two or more companies -> generate the comparison (share prices side by side,
revenue growth, profit margins, debt-to-equity, trends) -> record the client's
interests -> save the discussion snapshot -> search by client or company ->
reopen it exactly as it was.

This file holds only the user interface. Data retrieval lives in services/,
calculations in analytics/, and saving/searching in storage/.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from analytics.formatting import (
    NOT_AVAILABLE,
    format_date,
    format_money,
    format_multiple,
    format_percent,
    format_price,
    format_time_ago,
    format_timestamp,
)
from analytics.ratios import TREND_LABELS, format_ratio
from config import (
    ANALYSIS_PERIODS,
    APP_VERSION,
    CACHE_TTL_SECONDS,
    DEFAULT_PERIOD_LABEL,
    database_url,
    deployed_commit,
    describe_database_url,
    local_today,
    timezone_label,
    to_local,
)
from models.briefing import Briefing, RmNote
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
from ui import charts, tables, theme
from ui.theme import chip, esc, flag, html_block, section

st.set_page_config(page_title="Nimbus · Client discussions", page_icon="☁️", layout="wide")

POPULAR_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "MU", "JPM", "D05.SI", "O39.SI", "U11.SI"]


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
    st.session_state.setdefault("client_choice", NEW_CLIENT)  # existing client ID, or NEW_CLIENT


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


def render_company_cards(briefing: Briefing) -> None:
    """One card per company: name + ticker, large last close with coloured return, then market cap and P/E."""
    companies = briefing.companies
    per_row = min(len(companies), 3)
    for start in range(0, len(companies), per_row):
        columns = st.columns(per_row)
        for column, company in zip(columns, companies[start:start + per_row]):
            with column.container(border=True):
                html_block(f'<div class="nb-card-title" title="{esc(company.name)}">{esc(company.name)} '
                           f'{chip(company.ticker)}</div>')
                hpr = briefing.holding_period_returns.get(company.ticker)
                st.metric(
                    "Last close",
                    format_price(company.last_close, company.currency),
                    delta=f"{format_percent(hpr)} over {briefing.analysis_period}" if hpr is not None else None,
                    help="Adjusted closing price. The coloured figure is the holding-period return.",
                )
                pe_marker = flag(tables.PE_FLAG_TEXT) if tables.pe_is_unusual(company.pe_ratio) else ""
                html_block(
                    f'<div class="nb-muted">As of {esc(format_date(company.last_close_date))}</div>'
                    '<div class="nb-stats">'
                    f'<div class="nb-stat"><span class="nb-label">Market cap</span>'
                    f'<span class="nb-value">{esc(format_money(company.market_cap, company.currency))}</span></div>'
                    f'<div class="nb-stat"><span class="nb-label">P/E (trailing)</span>'
                    f'<span class="nb-value">{esc(format_multiple(company.pe_ratio))}{pe_marker}</span></div>'
                    '</div>'
                )


def render_comparison(briefing: Briefing) -> None:
    companies = briefing.companies
    if not companies:
        st.info("No company data to show.")
        return

    render_company_cards(briefing)
    if len(companies) < 2:
        with st.container(border=True):
            st.markdown("**Add another ticker to compare.**")
            st.caption("Only one company was retrieved. Add a second one above, or use Quick add, and generate again.")

    section("Share-price performance, side by side")
    chart = charts.price_chart(briefing)
    if chart is None:
        st.info("Not enough common trading days to draw a comparison chart.")
    else:
        st.altair_chart(chart)
        if briefing.price_window:
            st.caption(f"Rebased to 100 on {format_date(briefing.price_window[0])}; adjusted closes to "
                       f"{format_date(briefing.price_window[1])} on days all companies traded. Hover for prices.")

    section("Financial comparison")
    st.table(tables.comparison_styler(briefing))
    unusual = [c.ticker for c in companies if tables.pe_is_unusual(c.pe_ratio)]
    st.caption("Bold = best in row (lowest for debt ratios). Red = negative. N/A = not reported by Yahoo."
               + (f" ⚠ P/E above {tables.PE_UNUSUAL:.0f}x for {', '.join(unusual)}: earnings may be depressed "
                  "or include one-off items." if unusual else ""))
    for note in tables.comparison_notes(briefing):
        st.caption(note)
    with st.expander("How these measures are calculated"):
        st.markdown(
            "- **Return:** last ÷ first adjusted close over the dates all companies traded (includes dividends "
            "and splits). Historical, not a forecast.\n"
            "- **Revenue / net income growth:** latest fiscal year ÷ previous − 1; N/A if the previous year is "
            "zero or negative.\n"
            "- **Net profit margin:** net income ÷ revenue. **Operating margin:** operating income ÷ revenue.\n"
            "- **Debt-to-equity:** total debt ÷ shareholders' equity at the same fiscal year-end; N/M (not "
            "meaningful) when equity is zero or negative.\n"
            "- **Return on assets:** net income ÷ total assets. **Debt-to-assets:** total debt ÷ total assets.\n"
            "- Companies' fiscal years can end in different months; each column shows its own year-end.\n"
            "- **N/A** means Yahoo Finance did not report the inputs. Nimbus never substitutes zero."
        )

    render_trends(briefing)
    render_analyst_view(briefing)
    render_earnings(briefing)


def render_trends(briefing: Briefing) -> None:
    """Revenue growth, net margin and debt-to-equity for each reported fiscal year."""
    section("Trends over time (annual)")
    records = tables.trend_records(briefing)
    if not any(r["Value"] is not None for r in records):
        st.info("Yahoo Finance did not report enough annual statements to show trends.")
        return
    columns = st.columns(len(TREND_LABELS))
    for column, (key, label) in zip(columns, TREND_LABELS.items()):
        with column:
            st.markdown(f"**{label}**")
            chart = charts.trend_chart(records, key)
            if chart is None:
                st.caption("Not reported.")
            else:
                st.altair_chart(chart)
    with st.expander("Trend figures by fiscal year"):
        for key, label in TREND_LABELS.items():
            st.markdown(f"**{label}**")
            st.table(tables.trend_table(briefing, key))
    st.caption("Fiscal year = the calendar year in which each company's fiscal year ended. Growth needs the "
               "previous year, so the oldest year has no growth figure.")


def render_analyst_view(briefing: Briefing) -> None:
    section("Analyst view")
    chart = charts.ratings_chart(briefing)
    if chart is not None:
        st.altair_chart(chart)
    st.dataframe(tables.analyst_frame(briefing), hide_index=True, column_config=tables.analyst_columns())
    st.caption("Third-party analyst views from Yahoo Finance at retrieval time, not Nimbus recommendations. "
               "“None” = not reported by Yahoo.")


def render_earnings(briefing: Briefing) -> None:
    section("Earnings")
    st.dataframe(tables.earnings_frame(briefing), hide_index=True, column_config=tables.earnings_columns())
    unusual = [c.ticker for c in briefing.companies
               if tables.surprise_is_unusual((c.earnings or {}).get("last_surprise"))]
    st.caption("Scheduled dates can change. “None” = not reported by Yahoo."
               + (f" ⚠ {', '.join(unusual)}: surprise over 100%; reported EPS may include one-off items."
                  if unusual else ""))


def render_financials(briefing: Briefing) -> None:
    if not briefing.companies:
        st.info("No company data to show.")
        return
    for company in briefing.companies:
        with st.container(border=True):
            html_block(f'<div class="nb-card-title">{esc(company.name)} {chip(company.ticker)}</div>')
            if company.financials:
                years = sorted({y for values in company.financials.values() for y in values}, reverse=True)
                # Every standard line item is listed, so an item Yahoo does not report shows as N/A
                # instead of silently disappearing.
                items = list(dict.fromkeys([*yahoo.STATEMENT_ITEMS, *company.financials]))
                table = pd.DataFrame(
                    {
                        f"FY {format_date(y)}": [
                            format_money(company.financials.get(item, {}).get(y), company.financial_currency)
                            for item in items
                        ]
                        for y in years
                    },
                    index=items,
                )
                st.table(table)
            else:
                st.info("Yahoo Finance returned no financial statements for this company.")
            st.caption(f"Annual statements in {company.financial_currency or 'reporting currency'} · "
                       f"[{company.source_name}]({company.source_url}) · retrieved "
                       f"{format_timestamp(company.retrieved_at)}")


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
    render_news_status(briefing)
    st.caption(f"{len(items)} {'article' if len(items) == 1 else 'articles'}, newest first"
               + (" · ☆ Save to note keeps an article with your RM note" if can_pin else ""))

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
            text.markdown(f'<div class="nb-meta">{chip(item.ticker)} · {esc(item.publisher or "Publisher not provided")}'
                          f' · {esc(when)}</div>', unsafe_allow_html=True)
            text.markdown(md_text(item.summary) if item.summary else "_No summary provided by the source._")
            if can_pin:
                key = article_key(item)
                text.button("★ Saved to note" if key in pinned else "☆ Save to note", key=f"pin_{key}",
                            on_click=toggle_saved_article, args=(briefing.briefing_id, key))

    notes = [f"{company.ticker}: {md_text(w)}" for company in briefing.companies for w in company.warnings]
    if notes:
        st.caption("Notes: " + " · ".join(notes))


def render_news_status(briefing: Briefing) -> None:
    """Say why news is missing (fetch error vs. genuinely none) in one compact notice."""
    failed, empty, fallback, skipped = [], [], [], 0
    for company in briefing.companies:
        status = company.news_status or {}
        skipped += status.get("skipped") or 0
        if status.get("status") == "error":
            failed.append(f"**{company.ticker}**: {md_text(status.get('message') or 'unknown error')}")
        elif status.get("status") == "empty" or (status and not company.news):
            empty.append(company.ticker)
        elif status.get("source") == "Yahoo Finance search":
            fallback.append(company.ticker)
    if failed:
        st.warning("News could not be retrieved for some companies:  \n" + "  \n".join(failed)
                   + "  \nTry generating again in a few minutes; run `python scripts/debug_news.py "
                   + " ".join(c.ticker for c in briefing.companies) + "` to see Yahoo's raw response.")
    notes = []
    if empty:
        notes.append(f"Yahoo has no recent articles for {', '.join(empty)}.")
    if fallback:
        notes.append(f"{', '.join(fallback)}: Yahoo's news feed was empty, so articles come from Yahoo search.")
    if skipped:
        notes.append(f"{skipped} malformed article{'s' if skipped != 1 else ''} skipped.")
    if notes:
        st.caption(" ".join(notes))


def render_note(note: Optional[RmNote]) -> None:
    if not note:
        st.info("No discussion note was saved.")
        return
    with st.container(border=True):
        left, right = st.columns(2)
        left.markdown(f"**Client ID:** {md_text(note.client_id)}"
                      + (f" · {md_text(note.client_name)}" if note.client_name else ""))
        left.markdown(f"**Discussion date:** {format_date(note.discussion_date)}")
        right.markdown(f"**Next review date:** {format_date(note.next_review_date)}")
        right.markdown(f"**Note recorded:** {format_timestamp(note.created_at)}")
        for label, text in (
            ("Client's interests", note.client_interests),
            ("Discussion notes", note.notes),
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

@st.cache_resource
def server_started_at() -> str:
    """When this server process started (once per process). After an EC2 reboot this changes,
    which shows in the sidebar that the app really restarted."""
    return utc_now_iso()


def sidebar() -> None:
    with st.sidebar:
        theme.side_title("Quick add")
        columns = st.columns(3)
        for index, ticker in enumerate(POPULAR_TICKERS):
            columns[index % 3].button(ticker, key=f"quick_{ticker}", on_click=quick_add, args=(ticker,),
                                      width="stretch")

        theme.side_title("Recent discussions")
        try:
            recent = database.search_discussions(limit=5)
            if not recent:
                st.caption("🗂️ No saved discussions yet. Save one from **Discussion** and it appears here.")
        except Exception:
            recent = []
            st.caption("⚠️ Saved discussions are unavailable: the database cannot be reached.")
        for row in recent:
            when = row["discussion_date"]
            label = f"{row['client_id']} · {row['tickers']} · {when.day} {when.strftime('%b')}"
            st.button(label, key=f"recent_{row['discussion_id']}", on_click=open_from_sidebar,
                      args=(row["discussion_id"],), help=(row["client_interests"] or "")[:200] or None,
                      width="stretch")

        theme.side_title("About")
        with st.expander("About the data"):
            st.markdown(
                "- Market data, statements, ratings and news: **Yahoo Finance** (via yfinance)\n"
                f"- Retrieved data is reused for {CACHE_TTL_SECONDS // 60} minutes\n"
                "- Saved discussions are snapshots and are never refreshed\n"
                "- Figures are historical, not forecasts or advice"
            )
        commit = deployed_commit()
        st.caption(f"Nimbus {APP_VERSION}" + (f" · commit {commit}" if commit else "")
                   + f" · server started {format_timestamp(server_started_at())}")


def company_picker() -> None:
    """Search box, removable chips and a confirmation row of the chosen companies."""
    st.text_input(
        "Find companies",
        key="company_query",
        on_change=on_company_query,
        placeholder="Type a name or ticker and press Enter, e.g. nvidia, Google, MU, or a list: AAPL, MSFT, DBS",
        help="Company names and tickers both work. Separate several with commas. "
             f"Up to {MAX_COMPANIES} companies per comparison.",
    )

    feedback = st.session_state.get("lookup_feedback") or {}
    suggestions = feedback.get("suggestions") or []
    if suggestions:
        st.caption(f"Matches for “{md_text(feedback['query'])}”. Choose one to add:")
        for index, match in enumerate(suggestions):
            left, right = st.columns([6, 1], vertical_alignment="center")
            left.markdown(f"{esc(match.name)} {chip(match.ticker)}"
                          + (f' <span class="nb-muted">· {esc(match.exchange)}</span>' if match.exchange else ""),
                          unsafe_allow_html=True)
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
        "Companies to compare",
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
            name_col, ticker_col, exchange_col, choice_col = st.columns([3, 1, 1.2, 1.8], vertical_alignment="center")
            name_col.markdown(f"**{md_text(match.name)}**" + (f" · _typed “{md_text(typed)}”_" if typed else ""))
            ticker_col.markdown(chip(ticker), unsafe_allow_html=True)
            exchange_col.caption(match.exchange or ("Checked on generate" if match.source == "typed" else "—"))
            if alternatives:  # only where there is a real choice
                with choice_col.popover(f"⇄ {len(alternatives)} other match{'es' if len(alternatives) > 1 else ''}"):
                    options = [ticker] + [m.ticker for m in alternatives]
                    labels = {ticker: f"Keep {ticker}"}
                    labels.update({m.ticker: f"Use {m.label}" for m in alternatives})
                    st.selectbox("Use another listing", options, key=f"switch_{ticker}", format_func=labels.get,
                                 on_change=switch_listing, args=(ticker,))


NEW_CLIENT = "➕ New client"


def client_options() -> Dict[str, str]:
    """Existing clients for the selector: client_id -> label. Empty if the database is unreachable."""
    try:
        return {row["client_id"]: f"{row['client_id']}" + (f" · {row['client_name']}" if row["client_name"] else "")
                + f" ({row['discussions']} saved)" for row in database.list_clients()}
    except Exception:
        return {}


def selected_client() -> Tuple[Optional[str], Optional[str]]:
    """(client ID, client name) chosen at the top of the page; ID is None if nothing usable is entered."""
    choice = st.session_state.get("client_choice") or NEW_CLIENT
    if choice != NEW_CLIENT:
        return choice, None
    raw = (st.session_state.get("new_client_id") or "").strip()
    name = (st.session_state.get("new_client_name") or "").strip() or None
    try:
        return database.normalise_client_id(raw), name
    except ValueError:
        return None, name


def client_picker() -> None:
    """Step 1 of the workflow: choose an existing client or enter a new client ID."""
    options = client_options()
    choices = [NEW_CLIENT] + list(options)
    if st.session_state.get("client_choice") not in choices:
        st.session_state["client_choice"] = NEW_CLIENT
    choice_col, id_col, name_col = st.columns([1.6, 1, 1.4], vertical_alignment="bottom")
    choice = choice_col.selectbox("Client", choices, key="client_choice", format_func=lambda c: options.get(c, c),
                                  help="Choose a client you have met before, or New client to enter a client ID.")
    if choice == NEW_CLIENT:
        id_col.text_input("Client ID *", key="new_client_id", placeholder="e.g. C-1001", max_chars=32,
                          help="Letters, digits, - or _. Stored in capitals.")
        name_col.text_input("Client name (optional)", key="new_client_name", max_chars=200)
        typed = (st.session_state.get("new_client_id") or "").strip()
        if typed:
            try:
                database.normalise_client_id(typed)
            except ValueError as exc:
                id_col.caption(f"⚠️ {exc}")


def generate_section() -> None:
    with st.container(border=True):
        html_block('<div class="nb-card-title">New client discussion</div>')
        client_picker()
        company_picker()
        period_col, button_col, _ = st.columns([1.4, 1.6, 3], vertical_alignment="bottom")
        period_label = period_col.selectbox("Price period", list(ANALYSIS_PERIODS), key="period_label",
                                            help="Period for the share-price chart and returns")
        clicked = button_col.button("Generate comparison", type="primary", width="content")

    # The spinner and errors go in a container that exists on every run. If they were placed
    # directly on the page, the number of elements above the tabs would change between runs,
    # and Streamlit 1.50 (EC2) would then reset the tabs to Compare and drop half-typed notes.
    with st.container():
        if not clicked:
            return
        tickers = list(st.session_state["selected_tickers"])
        if len(tickers) < 2:
            st.error("Add at least two companies to generate a comparison.")
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


NOTE_FIELDS = ("date", "interests", "notes", "actions", "review", "other")


def note_values(briefing: Briefing, prefix: str = "") -> Dict[str, object]:
    """Current values of the note fields (prefix "" = Discussion tab, "dlg_" = save dialog)."""
    return {field: st.session_state.get(f"{prefix}{field}_{briefing.briefing_id}") for field in NOTE_FIELDS}


def note_is_complete(values: Dict[str, object]) -> bool:
    return bool(selected_client()[0] and (values.get("interests") or "").strip())


def missing_fields(values: Dict[str, object]) -> List[str]:
    missing = []
    if not selected_client()[0]:
        missing.append("a client (choose one, or enter a valid Client ID at the top of the page)")
    if not (values.get("interests") or "").strip():
        missing.append("notes about the client's interests")
    return missing


def perform_save(briefing: Briefing, values: Dict[str, object]) -> bool:
    """Save the discussion with the note built from `values`. Runs inside click handlers, i.e.
    before the page is redrawn, so the sidebar and the header show the saved state straight away.
    Returns True on success."""
    state = st.session_state
    missing = missing_fields(values)
    if missing:
        state["save_error"] = "Please add " + " and ".join(missing) + " before saving."
        return False
    client_id, client_name = selected_client()
    discussion_date, review_date = values.get("date") or local_today(), values.get("review")
    note = RmNote(
        client_id=client_id,
        client_name=client_name,
        discussion_date=discussion_date.isoformat(),
        client_interests=values["interests"].strip(),
        notes=(values.get("notes") or "").strip(),
        follow_up_actions=(values.get("actions") or "").strip(),
        next_review_date=review_date.isoformat() if review_date else None,
        free_text=(values.get("other") or "").strip(),
        created_at=utc_now_iso(),
        saved_articles=pinned_articles(briefing),
    )
    try:
        result = briefing_store.save_discussion(briefing, note)
    except Exception as exc:
        state["save_error"] = f"The discussion could not be saved: {exc}"
        return False
    state["saved"][briefing.briefing_id] = result.filename
    state["saved_note"] = result.briefing.note or note
    state["client_choice"] = client_id  # a new client is now an existing one: select it
    state.pop("save_error", None)
    state["toast"] = f"Discussion with {client_id} saved"
    return True


def save_from_form(briefing: Briefing) -> None:
    """'Save discussion' in the Discussion tab."""
    perform_save(briefing, note_values(briefing))


def save_from_header(briefing: Briefing) -> None:
    """'💾 Save discussion' in the header: save at once if the note is complete, else open the dialog."""
    values = note_values(briefing)
    if note_is_complete(values):
        perform_save(briefing, values)
    else:
        st.session_state["open_note_dialog"] = briefing.briefing_id


def save_from_dialog(briefing: Briefing) -> None:
    if not perform_save(briefing, note_values(briefing, prefix="dlg_")):
        st.session_state["open_note_dialog"] = briefing.briefing_id  # keep the dialog open to show the error


def note_fields(briefing: Briefing, prefix: str = "", prefill: Optional[Dict[str, object]] = None) -> None:
    """The discussion note inputs. The dialog (prefix "dlg_") starts from what was typed in the tab."""
    key = briefing.briefing_id
    prefill = prefill or {}

    def k(field: str) -> str:
        return f"{prefix}{field}_{key}"

    left, right = st.columns([1, 3])
    left.date_input("Discussion date *", value=prefill.get("date") or local_today(), key=k("date"))
    right.text_area("Client's interests *", key=k("interests"), value=prefill.get("interests") or "",
                    placeholder="What the client is interested in, e.g. dividend income, AI exposure, lower debt",
                    height=90)
    st.text_area("Discussion notes", key=k("notes"), value=prefill.get("notes") or "",
                 placeholder="What was discussed with the client?")
    left, right = st.columns(2)
    left.text_area("Follow-up actions", key=k("actions"), value=prefill.get("actions") or "")
    right.text_area("Other notes (optional)", key=k("other"), value=prefill.get("other") or "")
    left, _ = st.columns([1, 3])
    left.date_input("Next review date (optional)", value=prefill.get("review"), key=k("review"))


def client_line() -> str:
    client_id, client_name = selected_client()
    if not client_id:
        return "**Client:** ⚠️ none chosen yet. Choose or enter a Client ID at the top of the page."
    return f"**Client:** {chip(client_id)}" + (f" {esc(client_name)}" if client_name else "")


@st.dialog("Save discussion", width="large")
def note_dialog(briefing: Briefing) -> None:
    st.caption("Fields marked * are required. Anything typed in the Discussion tab is carried over.")
    st.markdown(client_line(), unsafe_allow_html=True)
    error = st.session_state.pop("save_error", None)
    if error:
        st.error(error)
    with st.form(f"dlg_note_form_{briefing.briefing_id}"):
        note_fields(briefing, prefix="dlg_", prefill=note_values(briefing))
        st.form_submit_button("💾 Save discussion", type="primary", on_click=save_from_dialog, args=(briefing,))


def data_retrieved_at(briefing: Briefing) -> str:
    """When Yahoo was actually asked for the oldest company data in the briefing.

    Retrieved data is reused for CACHE_TTL_SECONDS, so this can be earlier than the
    briefing's generation time (created_at)."""
    times = [company.retrieved_at for company in briefing.companies if company.retrieved_at]
    return min(times) if times else briefing.created_at


def briefing_header(briefing: Briefing) -> None:
    """Summary line, saved/unsaved indicator and a Save button that is visible from every tab."""
    saved = st.session_state["saved"].get(briefing.briefing_id)
    info_col, status_col, button_col = st.columns([5, 1.3, 1.6], vertical_alignment="center")
    retrieved = data_retrieved_at(briefing)
    when = f"generated {format_timestamp(briefing.created_at)}"
    if format_timestamp(retrieved) != format_timestamp(briefing.created_at):
        when += f" from data retrieved {format_timestamp(retrieved)}"
    info_col.caption(f"Comparison of {', '.join(briefing.successful_tickers)} · {when} · "
                     f"price period {briefing.analysis_period}")
    if saved:
        status_col.markdown(chip("✓ Saved", "up", tooltip=saved), unsafe_allow_html=True)
    else:
        status_col.markdown(chip("● Unsaved discussion", "warn",
                                 tooltip="Not saved yet. Save to keep it in History."),
                            unsafe_allow_html=True)
        button_col.button("💾 Save discussion", type="primary", key="header_save", width="content",
                          on_click=save_from_header, args=(briefing,))
    if st.session_state.pop("open_note_dialog", None) == briefing.briefing_id:
        note_dialog(briefing)


def notes_and_save_section(briefing: Optional[Briefing]) -> None:
    if briefing is None:
        st.info("Choose a client and generate a comparison first, then record the discussion here.")
        return
    saved_filename = st.session_state["saved"].get(briefing.briefing_id)
    if saved_filename:
        st.success("This discussion snapshot was saved.")
        st.caption(f"Find it under History or Recent discussions in the sidebar. File: {saved_filename}. "
                   "Generate a new comparison to start another discussion.")
        render_note(st.session_state.get("saved_note"))
        return
    if not briefing.companies:
        st.warning("There is no retrieved company data to save.")
        return

    st.markdown(client_line(), unsafe_allow_html=True)
    st.caption(
        f"Saved together with the comparison of {', '.join(briefing.successful_tickers)} "
        f"(stock prices, ratios and news as retrieved {format_timestamp(data_retrieved_at(briefing))}). "
        "Fields marked * are required."
    )
    articles = pinned_articles(briefing)
    if articles:
        st.markdown(f"**Articles to keep with this discussion ({len(articles)})**")
        st.markdown(render_article_list(articles))
    else:
        st.caption("Tip: use **Save to note** in the News tab to keep relevant articles with this discussion.")

    # Plain inputs (not an st.form), so what the RM types is always available to the header's
    # Save button and the save dialog, not only after this tab's own button is pressed.
    with st.container(border=True):
        note_fields(briefing)
        st.button("💾 Save discussion", type="primary", key="notes_save", on_click=save_from_form,
                  args=(briefing,))

    error = st.session_state.pop("save_error", None)
    if error:
        st.error(error)


ALL_CLIENTS = "All clients"


def history_section() -> None:
    url = database_url()
    try:
        counts = database.count_rows()
    except Exception as exc:
        st.error(f"Cannot reach the discussion database ({describe_database_url(url)}): {exc}")
        return

    def plural(count: int, word: str) -> str:
        return f"{count} {word}{'' if count == 1 else 's'}"

    st.caption(
        f"Database: {describe_database_url(url)} · {plural(counts['clients'], 'client')}, "
        f"{plural(counts['discussions'], 'discussion')}, "
        f"{plural(counts['discussion_companies'], 'company record')}."
    )

    options = client_options()
    with st.form("history_search_form"):
        c1, c2 = st.columns([1, 1])
        client = c1.selectbox("Client", [ALL_CLIENTS] + list(options), format_func=lambda c: options.get(c, c),
                              key="history_client")
        company = c2.text_input("Company (ticker or name)", placeholder="e.g. NVDA or nvidia", key="history_company")
        d1, d2, _ = st.columns([1, 1, 2])
        date_from = d1.date_input(f"Discussion from ({timezone_label()})", value=None)
        date_to = d2.date_input(f"Discussion to ({timezone_label()})", value=None)
        submitted = st.form_submit_button("Search")
    if submitted:
        if date_from and date_to and date_from > date_to:
            # Show only the error: listing the previous results under it would look like an answer.
            st.error("“Discussion from” is after “Discussion to”. Swap the dates and search again.")
            return
        st.session_state["history_filters"] = {
            "client_id": None if client == ALL_CLIENTS else client,
            "company": company,
            "date_from": date_from,
            "date_to": date_to,
        }
        st.session_state["open_briefing_id"] = None

    try:
        results = database.search_discussions(**st.session_state["history_filters"])
    except Exception as exc:
        st.error(f"Search failed: {exc}")
        return

    open_id = st.session_state.get("open_briefing_id")
    if not results and not open_id:
        st.info("No saved discussions match these filters.")
        return

    if results:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Discussion date": format_date(row["discussion_date"].isoformat()),
                        "Client": row["client_id"] + (f" · {row['client_name']}" if row["client_name"] else ""),
                        "Companies": row["tickers"],
                        "Client's interests": (row["client_interests"] or "")[:80],
                        f"Saved ({timezone_label()})": to_local(row["created_at"]).strftime("%Y-%m-%d %H:%M"),
                    }
                    for row in results
                ]
            ),
            hide_index=True,
        )
        labels = {
            row["discussion_id"]: f"{format_date(row['discussion_date'].isoformat())} · {row['client_id']} · "
            f"{row['tickers']}"
            for row in results
        }
        options_ids = list(labels)
        left, right = st.columns([4, 1], vertical_alignment="bottom")
        # Show the discussion that is open below (e.g. opened from the sidebar), so the selector and
        # the page never disagree. Keyed by the open discussion so the default follows it.
        chosen = left.selectbox("Choose a saved discussion", options_ids, format_func=labels.get,
                                index=options_ids.index(open_id) if open_id in options_ids else 0,
                                key=f"history_choice_{open_id or 'none'}")
        if right.button("Open discussion"):
            st.session_state["open_briefing_id"] = chosen
            open_id = chosen

    if open_id:
        render_historical(open_id)


def render_saved_values(discussion_id: str) -> None:
    """The per-company rows stored in the database: the values observed at the discussion."""
    rows = database.get_companies(discussion_id)
    if not rows:
        return
    frame = pd.DataFrame(
        {
            row["ticker"]: [
                row["company_name"] or row["ticker"],
                format_price(row["stock_price"], row["currency"]),
                format_date(row["price_date"].isoformat()) if row["price_date"] else NOT_AVAILABLE,
                format_ratio("revenue_growth", row["revenue_growth"]),
                format_ratio("net_margin", row["net_margin"]),
                format_ratio("operating_margin", row["operating_margin"]),
                format_ratio("debt_to_equity", row["debt_to_equity"]),
                format_date(row["fiscal_year_end"].isoformat()) if row["fiscal_year_end"] else NOT_AVAILABLE,
                row["source"],
            ]
            for row in rows
        },
        index=["Company", "Stock price at discussion", "Price date", "Revenue growth (YoY)", "Net profit margin",
               "Operating margin", "Debt-to-equity", "Ratios as of FY end", "Source"],
    )
    st.table(frame)
    st.caption("Read from the database (discussion_companies): the values recorded when this discussion was "
               "saved.")


def render_historical(briefing_id: str) -> None:
    try:
        briefing, row = briefing_store.open_discussion(briefing_id)
    except Exception as exc:
        st.error(f"Could not open the saved discussion: {exc}")
        return
    st.divider()
    left, right = st.columns([4, 1], vertical_alignment="bottom")
    client = row["client_id"] + (f" · {row['client_name']}" if row.get("client_name") else "")
    left.markdown(f'<div class="nb-section">Saved discussion · {esc(client)} · '
                  f'{esc(", ".join(briefing.successful_tickers))}</div>', unsafe_allow_html=True)
    right.download_button(
        "Download as Markdown",
        data=snapshots.markdown_for(briefing, row["filename"]),
        file_name=row["filename"],
        mime="text/markdown",
        key=f"download_{briefing_id}",
    )
    st.info(
        f"📁 **Historical snapshot.** Discussion on {format_date(row['discussion_date'].isoformat())}; saved "
        f"{format_timestamp(briefing.saved_at)}; data retrieved {format_timestamp(data_retrieved_at(briefing))}. "
        "These figures are exactly as saved; Nimbus has not retrieved current data."
    )
    render_notices(briefing)
    section("Discussion")
    render_note(briefing.note)
    section("Values at the time of the discussion")
    render_saved_values(briefing_id)
    section("Comparison as saved")
    render_comparison(briefing)
    section("Financial statements")
    render_financials(briefing)
    section("News")
    render_news_feed(briefing, live=False)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def main() -> None:
    init_state()
    theme.inject_css()
    sidebar()

    theme.header("Client discussions for relationship managers")
    generate_section()

    briefing: Optional[Briefing] = st.session_state.get("briefing")
    # Same reason as in generate_section: one container on every run, whatever it holds
    # (notices, the saved/unsaved header, the save dialog), keeps the tabs from resetting.
    with st.container():
        if briefing is not None:
            render_notices(briefing)
            if briefing.companies:
                briefing_header(briefing)

    toast = st.session_state.pop("toast", None)
    if toast:
        st.toast(toast, icon="✅")

    if st.session_state.pop("sidebar_opened", False):
        st.toast("Saved discussion opened in the History tab.", icon="📁")

    tabs = st.tabs(["📊 Compare", "📑 Financials", "📰 News", "📝 Discussion", "🗂️ History"])
    with tabs[0]:
        if briefing is None:
            st.info("Choose a client, add at least two companies above and select **Generate comparison**.")
        else:
            render_comparison(briefing)
    with tabs[1]:
        if briefing is None:
            st.info("Generate a comparison to see financial statements.")
        else:
            render_financials(briefing)
    with tabs[2]:
        if briefing is None:
            st.info("Generate a comparison to see the latest news for its companies.")
        else:
            render_news_feed(briefing, live=True)
    with tabs[3]:
        notes_and_save_section(briefing)
    with tabs[4]:
        history_section()


main()
