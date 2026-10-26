"""Show exactly what Yahoo Finance returns for news, and what Nimbus makes of it.

Usage (from the repository root, with the virtual environment active):

    python scripts/debug_news.py AAPL MSFT JPM O39.SI

For each ticker it prints:
  1. the raw result of yf.Ticker(t).get_news() - Yahoo's news feed;
  2. the raw news from yf.Search(t) - Yahoo's search service (Nimbus's fallback);
  3. any warnings yfinance logged instead of raising;
  4. how many articles Nimbus's parser extracts;
  5. for Yahoo search news: which tickers Yahoo links each article to, and
     whether it has a summary (Feature 1 needs a summary and a source);
  6. whether Yahoo's per-ticker RSS headline feed answers (a possible
     source of summaries; Nimbus does not use it yet).
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


def search_detail(ticker: str) -> None:
    """Per article from Yahoo search: linked tickers and whether a summary exists."""
    try:
        news = yf.Search(ticker, max_results=1, news_count=10).news or []
    except Exception as exc:
        print(f"  search detail unavailable: {exc}")
        return
    for article in news[:10]:
        related = article.get("relatedTickers") or []
        has_summary = bool(article.get("summary") or (article.get("content") or {}).get("summary"))
        mark = "KEEP" if ticker.upper() in [str(t).upper() for t in related] else "drop"
        print(f"    [{mark}] related={related} summary={'yes' if has_summary else 'no'} | "
              f"{str(article.get('title'))[:60]}")


def rss_probe(ticker: str) -> None:
    """Does Yahoo's RSS headline feed answer for this ticker, with summaries?"""
    import xml.etree.ElementTree as ET

    import requests

    url = "https://feeds.finance.yahoo.com/rss/2.0/headline"
    try:
        response = requests.get(url, params={"s": ticker, "region": "US", "lang": "en-US"},
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        print(f"  RSS feed: HTTP {response.status_code}, {len(response.content)} bytes")
        items = ET.fromstring(response.content).findall("./channel/item") if response.ok else []
    except Exception as exc:
        print(f"  RSS feed failed: {exc.__class__.__name__}: {exc}")
        return
    with_summary = sum(1 for item in items if (item.findtext("description") or "").strip())
    print(f"  RSS feed: {len(items)} items, {with_summary} with a summary")
    for item in items[:3]:
        print(f"    - {item.findtext('pubDate')} | {(item.findtext('title') or '')[:60]} | "
              f"summary: {(item.findtext('description') or '')[:60]!r}")


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
            print(f"    - {item.published_at} | {item.publisher} | {item.headline[:70]} | "
                  f"summary: {'yes' if item.summary else 'no'}")
        print("  Yahoo search articles (KEEP = linked to this ticker, as Nimbus now requires):")
        search_detail(ticker)
        rss_probe(ticker)
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or ["AAPL", "MSFT"])
