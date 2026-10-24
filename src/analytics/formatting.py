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
    """ISO date or date-time -> "4 Oct 2026"; unparseable input is shown as given."""
    if not value:
        return NOT_AVAILABLE
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return f"{parsed.day} {parsed.strftime('%b %Y')}"


def format_timestamp(value: Optional[str]) -> str:
    """ISO date-time -> "24 Oct 2026, 21:05 SGT", in the display time zone (NIMBUS_TIMEZONE).

    Values without a time zone are treated as UTC, which is how Nimbus stores them.
    """
    from config import timezone_label, to_local

    if not value:
        return NOT_AVAILABLE
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    local = to_local(parsed)
    return f"{local.day} {local.strftime('%b %Y, %H:%M')} {timezone_label(parsed)}"


def format_time_ago(value: Optional[str], now: Optional[datetime] = None) -> str:
    """ISO date-time -> "3h ago", "2d ago"; older than 30 days -> the date. None -> "N/A"."""
    if not value:
        return NOT_AVAILABLE
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    seconds = (now - parsed).total_seconds()
    if seconds < 0:
        return format_date(value)
    if seconds < 3600:
        return f"{max(int(seconds // 60), 1)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 30 * 86400:
        return f"{int(seconds // 86400)}d ago"
    return format_date(value)


def format_eps(value: Optional[float]) -> str:
    """Earnings per share: 1.6 -> "1.60"; None -> "N/A"."""
    return NOT_AVAILABLE if value is None else f"{value:,.2f}"
