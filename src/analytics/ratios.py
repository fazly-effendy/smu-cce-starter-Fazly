"""Normalized financial comparison measures (Feature 2).

All ratios use the company's own annual statements from Yahoo Finance, so
companies of different size become comparable. Definitions (latest fiscal
year = FY, previous fiscal year = FY-1):

    Revenue growth     = Revenue(FY) / Revenue(FY-1) - 1
    Net income growth  = Net income(FY) / Net income(FY-1) - 1
    Net profit margin  = Net income(FY) / Revenue(FY)
    Operating margin   = Operating income(FY) / Revenue(FY)
    Debt-to-equity     = Total debt / Shareholders' equity, both at FY year-end
    Return on assets   = Net income(FY) / Total assets at FY year-end
    Debt-to-assets     = Total debt / Total assets, both at FY year-end

A ratio is None (shown as N/A) when an input is missing or the denominator is
zero or negative. Growth from a zero or negative base is not meaningful and
is also N/A. Debt-to-equity with zero or negative equity is "not meaningful"
(N/M); see ratio_notes(). Balance-sheet values are matched to the same fiscal
year-end date as the income statement; if the dates differ, the ratio is N/A.

ratio_trends() applies the same definitions to every fiscal year Yahoo reports
(usually four), for the "trends over time" view.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from analytics.formatting import format_percent, format_times

# Order = order of rows in the comparison table. The first four are the measures the
# instructor asked for (revenue growth, profit margins, debt-to-equity).
RATIO_LABELS = {
    "revenue_growth": "Revenue growth (YoY)",
    "net_margin": "Net profit margin",
    "operating_margin": "Operating margin",
    "debt_to_equity": "Debt-to-equity",
    "net_income_growth": "Net income growth (YoY)",
    "return_on_assets": "Return on assets",
    "debt_to_assets": "Debt-to-assets",
}

# Ratios shown as a multiple (0.45x) rather than a percentage.
MULTIPLE_RATIOS = {"debt_to_equity"}

# Measures shown in the trends view, in this order.
TREND_LABELS = {
    "revenue_growth": "Revenue growth",
    "net_margin": "Net profit margin",
    "debt_to_equity": "Debt-to-equity",
}

NEGATIVE_EQUITY_NOTE = ("N/M: shareholders' equity is zero or negative (e.g. after large share buybacks), "
                        "so debt-to-equity is not meaningful.")

Financials = Dict[str, Dict[str, Optional[float]]]


def safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def growth_rate(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - 1.0


def reported_years(revenue: Dict[str, Optional[float]]) -> List[str]:
    """Fiscal year-ends with a reported revenue, newest first."""
    return sorted((date for date, value in revenue.items() if value is not None), reverse=True)


def latest_two_years(revenue: Dict[str, Optional[float]]) -> Tuple[Optional[str], Optional[str]]:
    """Most recent and previous fiscal year-ends that have a reported revenue."""
    years = reported_years(revenue)
    latest = years[0] if years else None
    previous = years[1] if len(years) > 1 else None
    return latest, previous


def _ratios_for_year(financials: Financials, year: Optional[str], previous: Optional[str]) -> Dict[str, Optional[float]]:
    revenue = financials.get("Revenue", {})
    operating_income = financials.get("Operating income", {})
    net_income = financials.get("Net income", {})
    assets = financials.get("Total assets", {})
    debt = financials.get("Total debt", {})
    equity = financials.get("Shareholders' equity", {})

    def value(item: Dict[str, Optional[float]], when: Optional[str]) -> Optional[float]:
        return item.get(when) if when else None

    return {
        "revenue_growth": growth_rate(value(revenue, year), value(revenue, previous)),
        "net_margin": safe_divide(value(net_income, year), value(revenue, year)),
        "operating_margin": safe_divide(value(operating_income, year), value(revenue, year)),
        "debt_to_equity": safe_divide(value(debt, year), value(equity, year)),
        "net_income_growth": growth_rate(value(net_income, year), value(net_income, previous)),
        "return_on_assets": safe_divide(value(net_income, year), value(assets, year)),
        "debt_to_assets": safe_divide(value(debt, year), value(assets, year)),
    }


def compute_ratios(financials: Financials) -> Tuple[Dict[str, Optional[float]], Optional[str], Optional[str]]:
    """Compute the comparison ratios for the latest fiscal year.

    Returns (ratios, latest fiscal year-end, previous fiscal year-end).
    """
    latest, previous = latest_two_years(financials.get("Revenue", {}))
    return _ratios_for_year(financials, latest, previous), latest, previous


def ratio_trends(financials: Financials) -> Dict[str, Dict[str, Optional[float]]]:
    """{fiscal year-end: ratios} for every reported year, oldest first (for trend charts).

    Growth needs the year before, so the oldest year has growth N/A.
    """
    years = list(reversed(reported_years(financials.get("Revenue", {}))))
    return {year: _ratios_for_year(financials, year, years[i - 1] if i > 0 else None)
            for i, year in enumerate(years)}


def format_ratio(key: str, value: Optional[float]) -> str:
    """Display a ratio: debt-to-equity as a multiple (0.45x), the rest as percentages."""
    return format_times(value) if key in MULTIPLE_RATIOS else format_percent(value)


def ratio_notes(financials: Financials, year: Optional[str]) -> Dict[str, str]:
    """Explanations for ratios that are deliberately not shown (key -> note)."""
    equity = (financials.get("Shareholders' equity") or {}).get(year) if year else None
    if equity is not None and equity <= 0:
        return {"debt_to_equity": NEGATIVE_EQUITY_NOTE}
    return {}
