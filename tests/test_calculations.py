"""Calculation and formatting tests (Features 1 and 2)."""

from __future__ import annotations

import pandas as pd
import pytest

from datetime import datetime, timezone

from analytics.formatting import (
    format_date,
    format_eps,
    format_money,
    format_multiple,
    format_percent,
    format_time_ago,
    format_timestamp,
)
from analytics.performance import align_prices, holding_period_returns, normalize_prices
from analytics.ratios import compute_ratios, growth_rate, safe_divide


# ---- formatting -----------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        (416_161_000_000, "$416.16B"),
        (3.5e12, "$3.50T"),
        (4_071_984_000, "$4.07B"),  # the raw number quoted in the Lesson 4 workshop
        (-2_500_000, "-$2.50M"),
        (12_345, "$12.35K"),
        (999, "$999.00"),
        (None, "N/A"),
    ],
)
def test_format_money(value, expected):
    assert format_money(value, "USD") == expected


def test_format_money_other_currency():
    assert format_money(1.2e9, "TWD") == "TWD 1.20B"


def test_percent_multiple_and_dates():
    assert format_percent(0.12345) == "12.3%"
    assert format_percent(-0.07) == "-7.0%"
    assert format_percent(0.0) == "0.0%"  # a genuine zero stays zero
    assert format_percent(None) == "N/A"
    assert format_multiple(33.456) == "33.5x"
    assert format_multiple(None) == "N/A"
    assert format_date("2026-10-20T12:00:00Z") == "20 Oct 2026"
    assert format_date(None) == "N/A"
    assert format_timestamp("2026-10-24T21:00:00+08:00") == "24 Oct 2026, 13:00 UTC"


# ---- share-price performance -------------------------------------------------

def _series(values, dates):
    return pd.Series(values, index=pd.to_datetime(dates), dtype=float)


def test_alignment_uses_only_common_dates():
    a = _series([100, 110, 121], ["2026-01-02", "2026-01-05", "2026-01-06"])
    b = _series([50, 55], ["2026-01-02", "2026-01-06"])  # missing 5 Jan
    aligned = align_prices({"A": a, "B": b})
    assert list(aligned.index.strftime("%Y-%m-%d")) == ["2026-01-02", "2026-01-06"]


def test_normalized_prices_start_at_100():
    a = _series([100, 110, 121], ["2026-01-02", "2026-01-05", "2026-01-06"])
    b = _series([50, 45, 60], ["2026-01-02", "2026-01-05", "2026-01-06"])
    normalized = normalize_prices(align_prices({"A": a, "B": b}))
    assert normalized.iloc[0].tolist() == [100.0, 100.0]
    assert normalized["A"].iloc[-1] == pytest.approx(121.0)
    assert normalized["B"].iloc[-1] == pytest.approx(120.0)


def test_holding_period_return():
    a = _series([100, 110, 121], ["2026-01-02", "2026-01-05", "2026-01-06"])
    b = _series([50, 45, 40], ["2026-01-02", "2026-01-05", "2026-01-06"])
    returns = holding_period_returns(align_prices({"A": a, "B": b}))
    assert returns["A"] == pytest.approx(0.21)
    assert returns["B"] == pytest.approx(-0.20)


def test_insufficient_price_data_gives_no_values_not_zero():
    a = _series([100], ["2026-01-02"])
    b = _series([50], ["2026-01-02"])
    aligned = align_prices({"A": a, "B": b})
    assert normalize_prices(aligned).empty
    assert holding_period_returns(aligned) == {"A": None, "B": None}


# ---- financial ratios -----------------------------------------------------------

def test_growth_and_division_rules():
    assert growth_rate(110, 100) == pytest.approx(0.10)
    assert growth_rate(50, -20) is None  # growth from a loss is not meaningful
    assert growth_rate(50, 0) is None
    assert growth_rate(None, 100) is None
    assert safe_divide(1, 0) is None
    assert safe_divide(None, 5) is None
    assert safe_divide(0, 5) == 0.0  # a real zero numerator is a real zero


def test_compute_ratios_with_full_data():
    financials = {
        "Revenue": {"2025-09-30": 416e9, "2024-09-30": 391e9},
        "Net income": {"2025-09-30": 112e9, "2024-09-30": 94e9},
        "Total assets": {"2025-09-30": 360e9, "2024-09-30": 365e9},
        "Total debt": {"2025-09-30": 100e9, "2024-09-30": 107e9},
    }
    ratios, latest, previous = compute_ratios(financials)
    assert (latest, previous) == ("2025-09-30", "2024-09-30")
    assert ratios["revenue_growth"] == pytest.approx(416 / 391 - 1)
    assert ratios["net_income_growth"] == pytest.approx(112 / 94 - 1)
    assert ratios["net_margin"] == pytest.approx(112 / 416)
    assert ratios["return_on_assets"] == pytest.approx(112 / 360)
    assert ratios["debt_to_assets"] == pytest.approx(100 / 360)


def test_missing_inputs_give_none_never_zero():
    ratios, latest, previous = compute_ratios({"Revenue": {"2025-06-30": 282e9}})
    assert latest == "2025-06-30" and previous is None
    assert all(value is None for value in ratios.values())


def test_balance_sheet_from_a_different_date_is_not_mixed_in():
    financials = {
        "Revenue": {"2025-12-31": 100.0, "2024-12-31": 90.0},
        "Net income": {"2025-12-31": 10.0, "2024-12-31": 9.0},
        "Total assets": {"2025-06-30": 200.0},  # mid-year balance sheet: different date
    }
    ratios, _, _ = compute_ratios(financials)
    assert ratios["return_on_assets"] is None
    assert ratios["net_margin"] == pytest.approx(0.10)


def test_time_ago_and_eps():
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    assert format_time_ago("2026-10-24T11:50:00Z", now) == "10m ago"
    assert format_time_ago("2026-10-24T09:00:00Z", now) == "3h ago"
    assert format_time_ago("2026-10-20T12:00:00Z", now) == "4d ago"
    assert format_time_ago("2026-08-01T12:00:00Z", now) == "1 Aug 2026"
    assert format_time_ago(None, now) == "N/A"
    assert format_eps(3.6) == "3.60" and format_eps(None) == "N/A"


# ---- instructor's comparison measures (Gaurav, 27 Oct 2026) --------------------------------

FOUR_YEARS = {
    "Revenue": {"2022-12-31": 100.0, "2023-12-31": 110.0, "2024-12-31": 121.0, "2025-12-31": 145.2},
    "Operating income": {"2022-12-31": 20.0, "2023-12-31": 22.0, "2024-12-31": 30.25, "2025-12-31": 43.56},
    "Net income": {"2022-12-31": 10.0, "2023-12-31": 11.0, "2024-12-31": 18.15, "2025-12-31": 29.04},
    "Total debt": {"2022-12-31": 50.0, "2023-12-31": 45.0, "2024-12-31": 40.0, "2025-12-31": 30.0},
    "Shareholders' equity": {"2022-12-31": 100.0, "2023-12-31": 90.0, "2024-12-31": 80.0, "2025-12-31": 60.0},
}


def test_debt_to_equity_and_operating_margin():
    ratios, latest, _ = compute_ratios(FOUR_YEARS)
    assert latest == "2025-12-31"
    assert ratios["debt_to_equity"] == pytest.approx(30 / 60)
    assert ratios["operating_margin"] == pytest.approx(43.56 / 145.2)


def test_trends_cover_every_reported_year_oldest_first():
    from analytics.ratios import ratio_trends

    trends = ratio_trends(FOUR_YEARS)
    assert list(trends) == ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
    assert trends["2022-12-31"]["revenue_growth"] is None  # no year before it
    assert [round(t["revenue_growth"], 3) for t in list(trends.values())[1:]] == [0.1, 0.1, 0.2]
    assert [round(t["net_margin"], 3) for t in trends.values()] == [0.1, 0.1, 0.15, 0.2]
    assert [round(t["debt_to_equity"], 3) for t in trends.values()] == [0.5, 0.5, 0.5, 0.5]


def test_negative_equity_makes_debt_to_equity_not_meaningful():
    from analytics.ratios import NEGATIVE_EQUITY_NOTE, ratio_notes

    financials = {"Revenue": {"2025-12-31": 100.0}, "Total debt": {"2025-12-31": 50.0},
                  "Shareholders' equity": {"2025-12-31": -5.0}}
    ratios, latest, _ = compute_ratios(financials)
    assert ratios["debt_to_equity"] is None
    assert ratio_notes(financials, latest) == {"debt_to_equity": NEGATIVE_EQUITY_NOTE}
    assert ratio_notes(FOUR_YEARS, "2025-12-31") == {}


def test_debt_to_equity_is_shown_as_a_multiple():
    from analytics.ratios import format_ratio

    assert format_ratio("debt_to_equity", 0.4512) == "0.45x"
    assert format_ratio("net_margin", 0.2) == "20.0%"
    assert format_ratio("debt_to_equity", None) == "N/A"
