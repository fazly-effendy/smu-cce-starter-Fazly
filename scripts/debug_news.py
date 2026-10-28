"""Show exactly what Yahoo Finance returns for news, and what Nimbus makes of it.

Usage (from the repository root, with the virtual environment active):

    python scripts/debug_news.py AAPL MSFT JPM O39.SI

For each ticker it prints:
  1. the raw result of yf.Ticker(t).get_news() - Yahoo's news feed;
  2. the raw news from yf.Search(t) - Yahoo's search service (Nimbus's fallback);
  3. any warnings yfinance logged instead of raising;
  4. how many articles Nimbus keeps, and whether each has a summary;
  5. every Yahoo search article with Nimbus's two relevance tests: is it linked to
     the ticker, and does its headline or summary name the company? Kept only if both;
  6. every item of Yahoo's per-ticker RSS headline feed: its fields (is there a
     publisher?), whether it has a summary, and whether it names the company;
  7. COVERAGE: how many kept search articles the RSS feed could give a summary to
     (matched by headline or link), and how many extra relevant RSS-only articles
     there are. Nimbus does not use the RSS feed yet: this measures whether it would help.
Copy the output into a message.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yfinance as yf  # noqa: E402

from services import yahoo  # noqa: E402

RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"


def preview(items, label: str) -> None:
    print(f"  {label}: type={type(items).__name__}, count={len(items) if items is not None else 'None'}")
    if items:
        first = items[0]
        print(f"    first item keys: {sorted(first.keys()) if isinstance(first, dict) else type(first).__name__}")
        if isinstance(first, dict) and isinstance(first.get("content"), dict):
            print(f"    first item content keys: {sorted(first['content'].keys())}")
        print("    first item (truncated):", json.dumps(first, default=str)[:600])


def normalise(text: Optional[str]) -> str:
    """Headline key for matching: lower case, letters and digits only ("Apple Wraps Up…" -> "applewrapsup…")."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def company_name(ticker: str) -> Optional[str]:
    """The company name Nimbus uses for the relevance test (from Yahoo, as in the app)."""
    try:
        return yahoo.extract_profile(yf.Ticker(ticker).info, ticker)["name"]
    except Exception as exc:
        print(f"  (company name unavailable: {exc.__class__.__name__}; using the ticker and Nimbus's aliases)")
        return None


def search_articles(ticker: str, name: Optional[str]) -> List[Dict[str, object]]:
    """Every Yahoo search article with Nimbus's two relevance tests."""
    try:
        news = yf.Search(ticker, max_results=1, news_count=10).news or []
    except Exception as exc:
        print(f"  search detail unavailable: {exc}")
        return []
    rows = []
    for article in news[:10]:
        if not isinstance(article, dict):
            continue
        related = [str(t).upper() for t in article.get("relatedTickers") or []]
        linked = ticker.upper() in related
        names = yahoo.mentions_company(yahoo._article_text(article), ticker, name)
        has_summary = bool(article.get("summary") or (article.get("content") or {}).get("summary"))
        rows.append({"title": str(article.get("title") or ""), "link": article.get("link"),
                     "publisher": article.get("publisher"), "linked": linked, "names": names,
                     "keep": linked and names, "summary": has_summary})
    return rows


def rss_items(ticker: str) -> Optional[List[Dict[str, object]]]:
    """All items of Yahoo's RSS headline feed for this ticker (None if it did not answer)."""
    import requests  # already installed with yfinance

    try:
        response = requests.get(RSS_URL, params={"s": ticker, "region": "US", "lang": "en-US"},
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        print(f"  RSS feed: HTTP {response.status_code}, {len(response.content)} bytes")
        if not response.ok:
            return None
        root = ET.fromstring(response.content)
    except Exception as exc:
        print(f"  RSS feed failed: {exc.__class__.__name__}: {exc}")
        return None
    items = []
    for item in root.findall("./channel/item"):
        fields = {child.tag: (child.text or "").strip() for child in item}
        items.append({
            "tags": sorted(fields),
            "title": fields.get("title", ""),
            "link": fields.get("link", ""),
            "date": fields.get("pubDate", ""),
            "summary": fields.get("description", ""),
            # Anything that could name the publisher, whatever the feed calls it.
            "publisher": next((value for tag, value in fields.items()
                               if any(word in tag.lower() for word in ("source", "creator", "author", "publisher"))
                               and value), None),
        })
    return items


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

        name = company_name(ticker)
        print(f"  Company name used for relevance: {name or '(none)'}")
        result = yahoo.fetch_news(ticker, name=name)
        items, skipped = yahoo.parse_news_with_count(result["items"], ticker, limit=10)
        print(f"  Nimbus: status={result['status']}, source={result['source']}, kept={len(items)}, "
              f"skipped={skipped}")
        if result["message"]:
            print(f"  Nimbus message: {result['message']}")

        print("  Yahoo search articles (linked = Yahoo links it to the ticker; names = headline/summary "
              "names the company; KEEP only if both):")
        search = search_articles(ticker, name)
        for row in search:
            print(f"    [{'KEEP' if row['keep'] else 'drop'}] linked={'yes' if row['linked'] else 'no '} "
                  f"names={'yes' if row['names'] else 'no '} summary={'yes' if row['summary'] else 'no'} | "
                  f"{row['publisher']} | {row['title'][:70]}")

        rss = rss_items(ticker)
        if rss is None:
            print()
            continue
        print(f"  RSS item fields: {rss[0]['tags'] if rss else '(no items)'}")
        print(f"  RSS items ({len(rss)}; names = headline/summary names the company):")
        for item in rss:
            names = yahoo.mentions_company(f"{item['title']} {item['summary']}", ticker, name)
            item["names"] = names
            print(f"    [{'names' if names else 'other'}] publisher={item['publisher'] or 'none'} "
                  f"| {item['date']} | {item['title'][:60]} | summary: {item['summary'][:70]!r}")

        # Coverage: which kept search articles the RSS feed could give a summary to.
        by_title = {normalise(item["title"]): item for item in rss if item["title"]}
        by_link = {item["link"]: item for item in rss if item["link"]}
        kept = [row for row in search if row["keep"]]
        matched_keys = set()
        print("  Kept search articles and an RSS summary for them:")
        with_summary = 0
        for row in kept:
            match = by_title.get(normalise(row["title"])) or by_link.get(row["link"])
            if match and match["summary"]:
                with_summary += 1
                matched_keys.add(normalise(match["title"]))
            print(f"    [{'RSS summary' if match and match['summary'] else 'no summary '}] {row['title'][:70]}")
        extra = [item for item in rss if item["names"] and item["summary"]
                 and normalise(item["title"]) not in matched_keys
                 and normalise(item["title"]) not in {normalise(r["title"]) for r in kept}]
        print(f"  COVERAGE {ticker}: kept search articles {len(kept)}, of which with an RSS summary "
              f"{with_summary}; extra relevant RSS-only articles with a summary {len(extra)} "
              f"(publisher in feed: {'yes' if any(i['publisher'] for i in rss) else 'no'})")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or ["AAPL", "MSFT"])
