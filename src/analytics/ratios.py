"""Normalized financial comparison measures (Feature 2).

All ratios use the company's own annual statements from Yahoo Finance, so
companies of different size become comparable. Definitions (latest fiscal
year = FY, previous fiscal year = FY-1):

    Revenue growth     = Revenue(FY) / Revenue(FY-1) - 1
    Net income growth  = Net income(FY) / Net income(FY-1) - 1
    Net profit margin  = Net income(FY) / Revenue(FY)
    Return on assets   = Net income(FY) / Total assets at FY year-end
    Debt-to-assets     = Total debt / Total assets, both at FY year-end

A ratio is None (shown as N/A) when an input is missing or the denominator is
zero or negative. Growth from a zero or negative base is not meaningful and
is also N/A. Balance-sheet values are matched to the same fiscal year-end
date as the income statement; if the dates differ, the ratio is N/A.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

RATIO_LABELS = {
    "revenue_growth": "Revenue growth (YoY)",
    "net_income_growth": "Net income growth (YoY)",
    "net_margin": "Net profit margin",
    "return_on_assets": "Return on assets",
    "debt_to_assets": "Debt-to-assets",
}


def safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def growth_rate(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - 1.0


def latest_two_years(revenue: Dict[str, Optional[float]]) -> Tuple[Optional[str], Optional[str]]:
    """Most recent and previous fiscal year-ends that have a reported revenue."""
    years = sorted((date for date, value in revenue.items() if value is not None), reverse=True)
    latest = years[0] if years else None
    previous = years[1] if len(years) > 1 else None
    return latest, previous


def compute_ratios(
    financials: Dict[str, Dict[str, Optional[float]]]
) -> Tuple[Dict[str, Optional[float]], Optional[str], Optional[str]]:
    """Compute the comparison ratios from extracted statement line items.

    Returns (ratios, latest fiscal year-end, previous fiscal year-end).
    """
    revenue = financials.get("Revenue", {})
    net_income = financials.get("Net income", {})
    assets = financials.get("Total assets", {})
    debt = financials.get("Total debt", {})

    latest, previous = latest_two_years(revenue)

    def value(item: Dict[str, Optional[float]], year: Optional[str]) -> Optional[float]:
        return item.get(year) if year else None

    ratios = {
        "revenue_growth": growth_rate(value(revenue, latest), value(revenue, previous)),
        "net_income_growth": growth_rate(value(net_income, latest), value(net_income, previous)),
        "net_margin": safe_divide(value(net_income, latest), value(revenue, latest)),
        "return_on_assets": safe_divide(value(net_income, latest), value(assets, latest)),
        "debt_to_assets": safe_divide(value(debt, latest), value(assets, latest)),
    }
    return ratios, latest, previous
