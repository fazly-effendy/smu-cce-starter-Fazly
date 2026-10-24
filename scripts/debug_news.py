"""Show exactly what Yahoo Finance returns for news, and what Nimbus makes of it.

Usage (from the repository root, with the virtual environment active):

    python scripts/debug_news.py AAPL MSFT JPM O39.SI

For each ticker it prints:
  1. the raw result of yf.Ticker(t).get_news() - Yahoo's news feed;
  2. the raw news from yf.Search(t) - Yahoo's search service (Nimbus's fallback);
  3. any warnings yfinance logged instead of raising;
  4. how many articles Nimbus's parser extracts.
Copy the output into a message if news is still missing.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yfinance as yf  # noqa: E402

from services import yahoo  # noqa: E402


def preview(items, label: str) -> None:
    print(f"  {label}: type={type(items).__name__}, count={len(items) if items is not None else 'None'}")
    if items:
        first = items[0]
        print(f"    first item keys: {sorted(first.keys()) if isinstance(first, dict) else type(first).__name__}")
        if isinstance(first, dict) and isinstance(first.get("content"), dict):
            print(f"    first item content keys: {sorted(first['content'].keys())}")
        print("    first item (truncated):", json.dumps(first, default=str)[:600])


def main(tickers) -> None:
    logging.basicConfig(level=logging.WARNING, format="    yfinance log: %(levelname)s %(message)s")
    print(f"yfinance {yf.__version__}\n")
    for ticker in tickers:
        print(f"=== {ticker}")
        try:
            preview(yf.Ticker(ticker).get_news(count=10, tab="news"), "Ticker.get_news()")
        except Exception as exc:
            print(f"  Ticker.get_news() raised {exc.__class__.__name__}: {exc}")
        try:
            preview(yf.Search(ticker, max_results=1, news_count=10).news, "Search(...).news")
        except Exception as exc:
            print(f"  Search(...).news raised {exc.__class__.__name__}: {exc}")
        result = yahoo.fetch_news(ticker)
        items, skipped = yahoo.parse_news_with_count(result["items"], ticker, limit=10)
        print(f"  Nimbus: status={result['status']}, source={result['source']}, parsed={len(items)}, "
              f"skipped={skipped}")
        if result["message"]:
            print(f"  Nimbus message: {result['message']}")
        for item in items[:3]:
            print(f"    - {item.published_at} | {item.publisher} | {item.headline[:70]}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or ["AAPL", "MSFT"])
