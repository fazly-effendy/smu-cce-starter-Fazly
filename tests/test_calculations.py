"""Calculation and formatting tests (Features 1 and 2)."""

from __future__ import annotations

import pandas as pd
import pytest

from analytics.formatting import format_date, format_money, format_multiple, format_percent, format_timestamp
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
