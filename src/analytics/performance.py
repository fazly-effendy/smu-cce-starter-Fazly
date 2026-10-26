"""Share-price comparison: normalized prices and holding-period returns.

Method
------
1. Keep only dates on which every selected company traded, so all series
   start and end on the same day (different exchange holidays otherwise
   make the comparison unfair).
2. Normalized price = adjusted close / adjusted close on the first common
   date x 100. Every company starts at 100, so lines show relative
   performance regardless of share-price level.
3. Holding-period return = last adjusted close / first adjusted close - 1
   over the same common window. Adjusted closes include dividends and
   splits, so this is a total return, not a forecast.
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

MIN_OBSERVATIONS = 2


def align_prices(prices: Dict[str, pd.Series]) -> pd.DataFrame:
    """Combine price series into one table restricted to common trading dates."""
    if not prices:
        return pd.DataFrame()
    table = pd.concat(prices, axis=1, join="inner").sort_index()
    return table.dropna(how="any")


def normalize_prices(aligned: pd.DataFrame) -> pd.DataFrame:
    """Rebase each column to 100 on the first common date.

    Returns an empty table when there are too few observations or a starting
    price is not positive, rather than producing misleading values.
    """
    if aligned.empty or len(aligned) < MIN_OBSERVATIONS:
        return pd.DataFrame()
    first = aligned.iloc[0]
    if (first <= 0).any():
        return pd.DataFrame()
    return aligned.divide(first) * 100.0


def holding_period_returns(aligned: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Return over the common window per ticker; None when it cannot be computed."""
    results: Dict[str, Optional[float]] = {}
    for ticker in aligned.columns:
        series = aligned[ticker].dropna()
        if len(series) < MIN_OBSERVATIONS or series.iloc[0] <= 0:
            results[ticker] = None
        else:
            results[ticker] = float(series.iloc[-1] / series.iloc[0] - 1.0)
    return results
