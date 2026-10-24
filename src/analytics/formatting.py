"""Readable number formatting (Feature 1). Missing values always show as N/A."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

NOT_AVAILABLE = "N/A"

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "SGD": "S$"}


def _prefix(currency: Optional[str]) -> str:
    if not currency:
        return ""
    return _CURRENCY_SYMBOLS.get(currency.upper(), f"{currency.upper()} ")


def format_money(value: Optional[float], currency: Optional[str] = "USD") -> str:
    """416161000000 -> "$416.16B"; -2.5e6 -> "-$2.50M"; None -> "N/A"."""
    if value is None:
        return NOT_AVAILABLE
    sign = "-" if value < 0 else ""
    amount = abs(value)
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if amount >= threshold:
            return f"{sign}{_prefix(currency)}{amount / threshold:,.2f}{suffix}"
    return f"{sign}{_prefix(currency)}{amount:,.2f}"


def format_price(value: Optional[float], currency: Optional[str] = "USD") -> str:
    if value is None:
        return NOT_AVAILABLE
    return f"{_prefix(currency)}{value:,.2f}"


def format_percent(value: Optional[float], decimals: int = 1) -> str:
    """0.1234 -> "12.3%". Values are fractions, not percentages."""
    if value is None:
        return NOT_AVAILABLE
    return f"{value * 100:,.{decimals}f}%"


def format_multiple(value: Optional[float]) -> str:
    """28.43 -> "28.4x" (used for P/E)."""
    if value is None:
        return NOT_AVAILABLE
    return f"{value:,.1f}x"


def format_date(value: Optional[str]) -> str:
    """ISO date or date-time -> "24 Oct 2026"; unparseable input is shown as given."""
    if not value:
        return NOT_AVAILABLE
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%d %b %Y")


def format_timestamp(value: Optional[str]) -> str:
    """ISO date-time -> "24 Oct 2026, 13:05 UTC"."""
    if not value:
        return NOT_AVAILABLE
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%d %b %Y, %H:%M UTC")
