"""Runtime configuration for Nimbus.

Values are read from environment variables each time they are requested, so the
same code runs in Codespaces (local defaults) and on EC2 (values supplied by
the instance environment) without edits. See .env.example.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Nimbus"
APP_VERSION = "0.2.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "analyses-data"

# Analysis periods offered in the UI, mapped to yfinance period codes.
ANALYSIS_PERIODS = {
    "1 month": "1mo",
    "3 months": "3mo",
    "6 months": "6mo",
    "1 year": "1y",
    "2 years": "2y",
    "5 years": "5y",
}
DEFAULT_PERIOD_LABEL = "1 year"

# How long retrieved market data is reused before Yahoo is called again.
CACHE_TTL_SECONDS = 15 * 60

# Number of news items kept per company.
NEWS_ITEMS_PER_TICKER = 5


def data_dir() -> Path:
    """Folder for briefing snapshot files (created on first use)."""
    configured = os.environ.get("NIMBUS_DATA_DIR")
    path = Path(configured).expanduser() if configured else DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    """SQLAlchemy URL for the metadata database (SQLite locally, RDS later)."""
    configured = os.environ.get("NIMBUS_DATABASE_URL")
    if configured:
        return configured
    return f"sqlite:///{data_dir() / 'nimbus.db'}"


def describe_database_url(url: str) -> str:
    """Database location safe to show in the UI: never includes a password."""
    if url.startswith("sqlite"):
        return "SQLite (local file)"
    head, _, tail = url.partition("@")
    driver = head.split("://", 1)[0]
    host = tail.split("/", 1)[0] if tail else "unknown host"
    return f"{driver} at {host}"
