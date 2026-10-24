"""Test setup: import from src/, use fake Yahoo data and a temporary database."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import fake_yahoo  # noqa: E402
from services import yahoo  # noqa: E402
from storage import database  # noqa: E402


# Optional: run the same tests against MySQL instead of SQLite, e.g.
#   NIMBUS_TEST_DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/nimbus_test python -m pytest
# Use an empty, throwaway database: its Nimbus tables are dropped before every test.
TEST_DATABASE_URL = os.environ.get("NIMBUS_TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Every test gets its own data folder and an empty database, and never touches Yahoo."""
    data_dir = tmp_path / "analyses-data"
    monkeypatch.setenv("NIMBUS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("NIMBUS_TIMEZONE", "UTC")  # tests that need Singapore time set it themselves
    if TEST_DATABASE_URL:
        monkeypatch.setenv("NIMBUS_DATABASE_URL", TEST_DATABASE_URL)
        engine = create_engine(TEST_DATABASE_URL)
        database.metadata.drop_all(engine)
        engine.dispose()
    else:
        monkeypatch.setenv("NIMBUS_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(yahoo, "yf", fake_yahoo.FakeYF)
    database._engines.clear()
    fake_yahoo.CALLS.clear()
    fake_yahoo.SEARCH_ONLINE = True
    fake_yahoo.NEWS_FEED_MODE = "ok"
    try:
        import streamlit as st

        st.cache_data.clear()
    except Exception:
        pass
    yield data_dir
    for engine in database._engines.values():
        engine.dispose()
    database._engines.clear()
