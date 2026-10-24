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
from ui import charts, tables, theme
from ui.theme import chip, esc, flag, html_block, section

st.set_page_config(page_title="Nimbus · Company briefings", page_icon="☁️", layout="wide")

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

    section("Financial comparison")
    st.table(tables.comparison_styler(briefing))
    unusual = [c.ticker for c in companies if tables.pe_is_unusual(c.pe_ratio)]
    st.caption("Bold = best in row (lowest for debt-to-assets). Red = negative. N/A = not reported by Yahoo."
               + (f" ⚠ P/E above {tables.PE_UNUSUAL:.0f}x for {', '.join(unusual)}: earnings may be depressed "
                  "or include one-off items." if unusual else ""))
    with st.expander("How these measures are calculated"):
        st.markdown(
            "- **Return:** last ÷ first adjusted close over the dates all companies traded (includes dividends "
            "and splits). Historical, not a forecast.\n"
            "- **Revenue / net income growth:** latest fiscal year ÷ previous − 1; N/A if the previous year is "
            "zero or negative.\n"
            "- **Net profit margin:** net income ÷ revenue. **Return on assets:** net income ÷ total assets.\n"
            "- **Debt-to-assets:** total debt ÷ total assets, at the same fiscal year-end.\n"
            "- **N/A** means Yahoo Finance did not report the inputs. Nimbus never substitutes zero."
        )

    section("Share-price performance")
    chart = charts.price_chart(briefing)
    if chart is None:
        st.info("Not enough common trading days to draw a comparison chart.")
    else:
        st.altair_chart(chart)
        if briefing.price_window:
            st.caption(f"Rebased to 100 on {format_date(briefing.price_window[0])}; adjusted closes to "
                       f"{format_date(briefing.price_window[1])} on days all companies traded. Hover for prices.")

    render_analyst_view(briefing)
    render_earnings(briefing)


def render_analyst_view(briefing: Briefing) -> None:
    section("Analyst view")
    chart = charts.ratings_chart(briefing)
    if chart is not None:
        st.altair_chart(chart)
    st.dataframe(tables.analyst_frame(briefing), hide_index=True, column_config=tables.analyst_columns())
    st.caption("Third-party analyst views from Yahoo Finance at retrieval time, not Nimbus recommendations. "
               "Blank = not reported.")


def render_earnings(briefing: Briefing) -> None:
    section("Earnings")
    st.dataframe(tables.earnings_frame(briefing), hide_index=True, column_config=tables.earnings_columns())
    unusual = [c.ticker for c in briefing.companies
               if tables.surprise_is_unusual((c.earnings or {}).get("last_surprise"))]
    st.caption("Scheduled dates can change. Blank = not reported."
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
        theme.side_title("Quick add")
        columns = st.columns(3)
        for index, ticker in enumerate(POPULAR_TICKERS):
            columns[index % 3].button(ticker, key=f"quick_{ticker}", on_click=quick_add, args=(ticker,),
                                      width="stretch")

        theme.side_title("Recent briefings")
        try:
            recent = database.search_briefings(limit=5)
            if not recent:
                st.caption("🗂️ No saved briefings yet. Save one from **Notes** and it appears here.")
        except Exception:
            recent = []
            st.caption("⚠️ Saved briefings are unavailable: the database cannot be reached.")
        for row in recent:
            label = f"{row['tickers']} · {row['saved_at'].day} {row['saved_at'].strftime('%b %H:%M')}"
            st.button(label, key=f"recent_{row['briefing_id']}", on_click=open_from_sidebar,
                      args=(row["briefing_id"],), help=row["client_reference"] or None, width="stretch")

        theme.side_title("About")
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


def generate_section() -> None:
    with st.container(border=True):
        html_block('<div class="nb-card-title">New briefing</div>')
        company_picker()
        period_col, button_col, _ = st.columns([1.4, 1.6, 3], vertical_alignment="bottom")
        period_label = period_col.selectbox("Price period", list(ANALYSIS_PERIODS), key="period_label",
                                            help="Period for the share-price chart and returns")
        clicked = button_col.button("Generate briefing", type="primary", width="content")

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


NOTE_FIELDS = ("ref", "meeting", "summary", "priorities", "actions", "review", "other")


def note_values(briefing: Briefing, prefix: str = "") -> Dict[str, object]:
    """Current values of the note fields (prefix "" = Notes tab form, "dlg_" = save dialog)."""
    return {field: st.session_state.get(f"{prefix}{field}_{briefing.briefing_id}") for field in NOTE_FIELDS}


def note_is_complete(values: Dict[str, object]) -> bool:
    return bool((values.get("ref") or "").strip() and (values.get("summary") or "").strip())


def perform_save(briefing: Briefing, values: Dict[str, object]) -> bool:
    """Save the briefing with the RM note built from `values`. Runs inside click handlers, i.e.
    before the page is redrawn, so the sidebar's Recent briefings and the header show the saved
    state straight away. Returns True on success."""
    state = st.session_state
    if not note_is_complete(values):
        state["save_error"] = "Please enter a client or briefing reference and a discussion summary before saving."
        return False
    meeting_date, review_date = values.get("meeting"), values.get("review")
    note = RmNote(
        client_reference=values["ref"].strip(),
        meeting_date=meeting_date.isoformat() if meeting_date else None,
        discussion_summary=values["summary"].strip(),
        client_priorities=(values.get("priorities") or "").strip(),
        follow_up_actions=(values.get("actions") or "").strip(),
        next_review_date=review_date.isoformat() if review_date else None,
        free_text=(values.get("other") or "").strip(),
        created_at=utc_now_iso(),
        saved_articles=pinned_articles(briefing),
    )
    try:
        result = briefing_store.save_briefing(briefing, note)
    except Exception as exc:
        state["save_error"] = f"The briefing could not be saved: {exc}"
        return False
    state["saved"][briefing.briefing_id] = result.filename
    state["saved_note"] = result.briefing.note or note
    state.pop("save_error", None)
    state["toast"] = f"Briefing saved as {result.filename}"
    return True


def save_from_form(briefing: Briefing) -> None:
    """'Save briefing and RM notes' in the Notes tab."""
    perform_save(briefing, note_values(briefing))


def save_from_header(briefing: Briefing) -> None:
    """'💾 Save briefing' in the header: save at once if the note is filled in, else open the note dialog."""
    values = note_values(briefing)
    if note_is_complete(values):
        perform_save(briefing, values)
    else:
        st.session_state["open_note_dialog"] = briefing.briefing_id


def save_from_dialog(briefing: Briefing) -> None:
    if not perform_save(briefing, note_values(briefing, prefix="dlg_")):
        st.session_state["open_note_dialog"] = briefing.briefing_id  # keep the dialog open to show the error


def note_fields(briefing: Briefing, prefix: str = "", prefill: Optional[Dict[str, object]] = None) -> None:
    """The RM note inputs. The dialog (prefix "dlg_") starts from what was typed in the Notes tab."""
    key = briefing.briefing_id
    prefill = prefill or {}

    def k(field: str) -> str:
        return f"{prefix}{field}_{key}"

    left, right = st.columns(2)
    left.text_input("Client or briefing reference *", placeholder="e.g. Acme Holdings – Q4 review", key=k("ref"),
                    value=prefill.get("ref") or "")
    right.date_input("Meeting date", value=prefill.get("meeting") or date.today(), key=k("meeting"))
    st.text_area("Discussion summary *", placeholder="What was discussed with the client?", key=k("summary"),
                 value=prefill.get("summary") or "")
    left, right = st.columns(2)
    left.text_area("Client priorities or concerns", key=k("priorities"), value=prefill.get("priorities") or "")
    right.text_area("Follow-up actions", key=k("actions"), value=prefill.get("actions") or "")
    left, right = st.columns([1, 3])
    left.date_input("Next review date (optional)", value=prefill.get("review"), key=k("review"))
    right.text_area("Other notes (optional)", key=k("other"), height=68, value=prefill.get("other") or "")


@st.dialog("Save briefing", width="large")
def note_dialog(briefing: Briefing) -> None:
    st.caption("Add the required note fields (*) to save this briefing. Anything typed in the Notes tab is "
               "carried over.")
    error = st.session_state.pop("save_error", None)
    if error:
        st.error(error)
    with st.form(f"dlg_note_form_{briefing.briefing_id}"):
        note_fields(briefing, prefix="dlg_", prefill=note_values(briefing))
        st.form_submit_button("💾 Save briefing and RM notes", type="primary", on_click=save_from_dialog,
                              args=(briefing,))


def briefing_header(briefing: Briefing) -> None:
    """Summary line, saved/unsaved indicator and a Save button that is visible from every tab."""
    saved = st.session_state["saved"].get(briefing.briefing_id)
    info_col, status_col, button_col = st.columns([5, 1.2, 1.6], vertical_alignment="center")
    info_col.caption(f"Briefing for {', '.join(briefing.successful_tickers)} · generated "
                     f"{format_timestamp(briefing.created_at)} · price period {briefing.analysis_period}")
    if saved:
        status_col.markdown(chip("✓ Saved", "up", tooltip=saved), unsafe_allow_html=True)
    else:
        status_col.markdown(chip("● Unsaved briefing", "warn",
                                 tooltip="Not saved yet. Save to keep it in Briefing history."),
                            unsafe_allow_html=True)
        button_col.button("💾 Save briefing", type="primary", key="header_save", width="content",
                          on_click=save_from_header, args=(briefing,))
    if st.session_state.pop("open_note_dialog", None) == briefing.briefing_id:
        note_dialog(briefing)


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

    # Plain inputs (not an st.form), so what the RM types is always available to the header's
    # Save button and the save dialog, not only after this tab's own button is pressed.
    with st.container(border=True):
        note_fields(briefing)
        st.button("💾 Save briefing and RM notes", type="primary", key="notes_save", on_click=save_from_form,
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
    left.markdown(f'<div class="nb-section">Saved briefing · {esc(", ".join(briefing.successful_tickers))}</div>',
                  unsafe_allow_html=True)
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
    section("RM notes")
    render_note(briefing.note)
    section("Company comparison")
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

    theme.header("Company briefings for relationship managers")
    generate_section()

    briefing: Optional[Briefing] = st.session_state.get("briefing")
    if briefing is not None:
        render_notices(briefing)
        if briefing.companies:
            briefing_header(briefing)

    toast = st.session_state.pop("toast", None)
    if toast:
        st.toast(toast, icon="✅")

    if st.session_state.pop("sidebar_opened", False):
        st.toast("Saved briefing opened in the History tab.", icon="📁")

    tabs = st.tabs(["📊 Compare", "📑 Financials", "📰 News", "📝 Notes", "🗂️ History"])
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
