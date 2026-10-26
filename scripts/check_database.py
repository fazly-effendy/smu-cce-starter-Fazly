"""Check that Nimbus can reach its metadata database and create its tables.

Run from the project folder:
    python scripts/check_database.py

It uses the same settings as the app (NIMBUS_DATABASE_URL, otherwise local
SQLite). It never prints the password: only the driver, host and row counts.
Exit code 0 = connected and tables ready; 1 = could not connect.

EC2 user data runs this before telling CloudFormation the stack is complete,
so CREATE_COMPLETE also means the app server can reach RDS.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import database_url, describe_database_url  # noqa: E402
from storage import database  # noqa: E402


def main(attempts: int = 10, wait_seconds: int = 15) -> int:
    url = database_url()
    where = describe_database_url(url)
    for attempt in range(1, attempts + 1):
        try:
            counts = database.count_rows(database.get_engine(url))
        except Exception as exc:  # report the failure type, never the URL
            print(f"Attempt {attempt}/{attempts}: cannot reach {where}: {type(exc).__name__}: {exc}"[:500])
            database._engines.clear()
            if attempt < attempts:
                time.sleep(wait_seconds)
            continue
        print(f"Connected to {where}. Tables ready. Row counts: {counts}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
