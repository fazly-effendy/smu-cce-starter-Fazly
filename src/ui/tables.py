"""Table builders for the Compare tab.

- comparison_styler(): the financial comparison as a static table, with the best
  value per row in bold and negative values in red.
- analyst_frame() / earnings_frame(): data for st.dataframe with column_config,
  so numbers are right-aligned, formatted and headers stay short (detail in the
  header tooltip). Colour in these two uses small markers (🟢 ⚪ 🔴) rather than
  a pandas Styler, because a Styler replaces column_config number formatting on
  some Streamlit versions.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from analytics.formatting import NOT_AVAILABLE, format_date, format_money, format_multiple, format_percent, format_price
from analytics.ratios import RATIO_LABELS
from models.briefing import Briefing
from ui.theme import DOWN

PE_UNUSUAL = 100.0  # trailing P/E above this is flagged
SURPRISE_UNUSUAL = 1.0  # EPS surprise above 100% (either way) is flagged
PE_FLAG_TEXT = "Unusually high P/E: earnings may be depressed or include one-off items."
SURPRISE_FLAG_TEXT = "Unusually large surprise: reported EPS may include one-off items."

HIGHER_IS_BETTER = {"return", "revenue_growth", "net_income_growth", "net_margin", "return_on_assets"}
LOWER_IS_BETTER = {"debt_to_assets"}
CONSENSUS_MARK = {"strong buy": "🟢", "buy": "🟢", "outperform": "🟢", "hold": "⚪", "underperform": "🔴",
                  "sell": "🔴", "strong sell": "🔴"}
RESULT_MARK = {"beat": "🟢 Beat", "miss": "🔴 Miss", "in line": "⚪ In line"}


def pe_is_unusual(pe: Optional[float]) -> bool:
    return pe is not None and pe > PE_UNUSUAL


def surprise_is_unusual(surprise: Optional[float]) -> bool:
    return surprise is not None and abs(surprise) > SURPRISE_UNUSUAL


# --------------------------------------------------------------------------
# Financial comparison
# --------------------------------------------------------------------------

def comparison_rows(briefing: Briefing) -> List[Tuple[str, Optional[str], List[str], List[Optional[float]]]]:
    """(row label, measure key, display values, raw values) for each row of the comparison table."""
    companies = briefing.companies
    returns = [briefing.holding_period_returns.get(c.ticker) for c in companies]
    rows = [
        ("Last close", None, [format_price(c.last_close, c.currency) for c in companies], [None] * len(companies)),
        ("Price date", None, [format_date(c.last_close_date) for c in companies], [None] * len(companies)),
        (f"Return ({briefing.analysis_period})", "return", [format_percent(r) for r in returns], returns),
        ("Market cap", None, [format_money(c.market_cap, c.currency) for c in companies], [None] * len(companies)),
        ("P/E (trailing)", None,
         [format_multiple(c.pe_ratio) + (" ⚠" if pe_is_unusual(c.pe_ratio) else "") for c in companies],
         [None] * len(companies)),
    ]
    for key, label in RATIO_LABELS.items():
        values = [c.ratios.get(key) for c in companies]
        rows.append((label, key, [format_percent(v) for v in values], values))
    rows.append(("Ratios as of FY end", None,
                 [format_date(c.fiscal_year_end) if c.fiscal_year_end else NOT_AVAILABLE for c in companies],
                 [None] * len(companies)))
    return rows


def comparison_table(briefing: Briefing) -> pd.DataFrame:
    rows = comparison_rows(briefing)
    return pd.DataFrame([r[2] for r in rows], index=[r[0] for r in rows],
                        columns=[c.ticker for c in briefing.companies])


def comparison_styler(briefing: Briefing):
    """The comparison table with the best value per row in bold and negatives in red."""
    styles = comparison_styles(briefing)
    return comparison_table(briefing).style.apply(lambda _: styles, axis=None)


def comparison_styles(briefing: Briefing) -> pd.DataFrame:
    """CSS for each cell: bold for the best value in comparable rows, red for negatives."""
    rows = comparison_rows(briefing)
    table = comparison_table(briefing)
    styles = pd.DataFrame("", index=table.index, columns=table.columns)
    for label, key, _, raw in rows:
        known = [v for v in raw if v is not None]
        for column, value in zip(table.columns, raw):
            css = []
            if value is not None and value < 0:
                css.append(f"color: {DOWN}")
            if key and len(known) >= 2 and value is not None:
                best = max(known) if key in HIGHER_IS_BETTER else min(known) if key in LOWER_IS_BETTER else None
                if best is not None and value == best:
                    css.append("font-weight: 700")
            styles.loc[label, column] = "; ".join(css)
    return styles


# --------------------------------------------------------------------------
# Analyst view
# --------------------------------------------------------------------------

def analyst_frame(briefing: Briefing) -> pd.DataFrame:
    records = []
    for company in briefing.companies:
        view = company.analyst or {}
        consensus = view.get("recommendation")
        upside = view.get("upside")
        records.append({
            "Company": company.ticker,
            "Consensus": f"{CONSENSUS_MARK.get(consensus, '⚪')} {consensus.title()}" if consensus else None,
            "Analysts": view.get("analysts"),
            "Ccy": company.currency,
            "Target": view.get("target_mean"),
            "Upside": upside * 100 if upside is not None else None,
            "Low": view.get("target_low"),
            "High": view.get("target_high"),
        })
    return pd.DataFrame(records)


def analyst_columns() -> Dict[str, object]:
    cc = st.column_config
    return {
        "Company": cc.TextColumn("Company", width="small"),
        "Consensus": cc.TextColumn("Consensus", help="Yahoo Finance analyst consensus recommendation"),
        "Analysts": cc.NumberColumn("Analysts", format="%d", help="Number of analyst opinions"),
        "Ccy": cc.TextColumn("Ccy", width="small", help="Currency of the price targets"),
        "Target": cc.NumberColumn("Mean target", format="%.2f", help="Mean analyst price target"),
        "Upside": cc.NumberColumn("Upside", format="%+.1f%%", help="Mean target ÷ last close − 1"),
        "Low": cc.NumberColumn("Low", format="%.2f", help="Lowest analyst price target"),
        "High": cc.NumberColumn("High", format="%.2f", help="Highest analyst price target"),
    }


# --------------------------------------------------------------------------
# Earnings
# --------------------------------------------------------------------------

def _as_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def earnings_frame(briefing: Briefing) -> pd.DataFrame:
    records = []
    for company in briefing.companies:
        e = company.earnings or {}
        surprise = e.get("last_surprise")
        result = RESULT_MARK.get(e.get("last_result") or "", None)
        if result and surprise_is_unusual(surprise):
            result += " ⚠"
        records.append({
            "Company": company.ticker,
            "Next date": _as_date(e.get("next_date")),
            "Next EPS est.": e.get("next_eps_estimate"),
            "Last date": _as_date(e.get("last_date")),
            "EPS actual": e.get("last_eps_actual"),
            "EPS est.": e.get("last_eps_estimate"),
            "Surprise": surprise * 100 if surprise is not None else None,
            "Result": result,
        })
    frame = pd.DataFrame(records)
    for column in ("Next date", "Last date"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def earnings_columns() -> Dict[str, object]:
    cc = st.column_config
    return {
        "Company": cc.TextColumn("Company", width="small"),
        "Next date": cc.DateColumn("Next", format="D MMM YYYY", help="Next scheduled earnings date"),
        "Next EPS est.": cc.NumberColumn("Est. EPS", format="%.2f", help="Analyst EPS estimate for the next report"),
        "Last date": cc.DateColumn("Last", format="D MMM YYYY", help="Most recent reported quarter"),
        "EPS actual": cc.NumberColumn("Actual", format="%.2f", help="Reported EPS, most recent quarter"),
        "EPS est.": cc.NumberColumn("Estimate", format="%.2f", help="Analyst EPS estimate for that quarter"),
        "Surprise": cc.NumberColumn("Surprise", format="%+.1f%%",
                                    help="(Actual − estimate) ÷ |estimate|. Over ±100% is marked ⚠ unusual."),
        "Result": cc.TextColumn("Result", help="Beat or miss against the estimate. ⚠ = " + SURPRISE_FLAG_TEXT),
    }
