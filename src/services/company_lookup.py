"""Find companies by name or ticker (Feature 1 usability).

resolve_company("nvidia")  -> [CompanyMatch(ticker="NVDA", name="NVIDIA Corporation", exchange="NASDAQ"), ...]

Order of lookup:
1. A local dictionary of well-known company names (fast, works offline).
2. Yahoo Finance search (yfinance Search), keeping equities only and ranking
   primary US listings first, then other primary exchanges, then
   over-the-counter listings. Yahoo's own relevance order breaks ties.
3. If Yahoo cannot be reached, a ticker-shaped entry (e.g. "MU", "D05.SI") is
   accepted as typed and checked when the briefing is generated.

The search function is passed in, so the app can supply a cached version and
tests can supply a fake. Exchanges are taken from Yahoo rather than hard-coded
because listings change.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

MAX_COMPANIES = 6

SearchFunction = Callable[[str], List[dict]]

_TICKER_SHAPE = re.compile(r"^\^?[A-Z0-9]{1,6}([.\-][A-Z0-9]{1,3})?$")
_SUFFIX_WORDS = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
                 "holdings", "group", "the", "sa", "ag", "nv", "class", "a", "b", "c"}
US_PRIMARY = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS"}
OVER_THE_COUNTER = {"PNK", "OQB", "OQX", "OBB", "OEM", "OGM"}

# Common company names -> primary Yahoo Finance ticker. Keys are lower case.
COMPANY_TICKERS: Dict[str, str] = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL", "meta": "META",
    "facebook": "META", "meta platforms": "META", "amazon": "AMZN", "nvidia": "NVDA", "tesla": "TSLA",
    "netflix": "NFLX", "micron": "MU", "micron technology": "MU", "intel": "INTC", "amd": "AMD",
    "advanced micro devices": "AMD", "ibm": "IBM", "oracle": "ORCL", "salesforce": "CRM", "adobe": "ADBE",
    "cisco": "CSCO", "qualcomm": "QCOM", "broadcom": "AVGO", "tsmc": "TSM",
    "taiwan semiconductor": "TSM", "uber": "UBER", "airbnb": "ABNB", "paypal": "PYPL", "shopify": "SHOP",
    "alibaba": "BABA", "sony": "SONY", "toyota": "TM",
    "jpmorgan": "JPM", "jp morgan": "JPM", "jpmorgan chase": "JPM", "goldman sachs": "GS", "goldman": "GS",
    "morgan stanley": "MS", "bank of america": "BAC", "citigroup": "C", "citi": "C", "wells fargo": "WFC",
    "visa": "V", "mastercard": "MA", "american express": "AXP", "amex": "AXP", "blackrock": "BLK",
    "berkshire hathaway": "BRK-B", "berkshire": "BRK-B", "hsbc": "HSBC",
    "walmart": "WMT", "costco": "COST", "coca-cola": "KO", "coca cola": "KO", "coke": "KO", "pepsi": "PEP",
    "pepsico": "PEP", "mcdonalds": "MCD", "mcdonald's": "MCD", "nike": "NKE", "disney": "DIS",
    "starbucks": "SBUX", "procter & gamble": "PG", "procter and gamble": "PG", "exxon": "XOM",
    "exxonmobil": "XOM", "exxon mobil": "XOM", "chevron": "CVX", "boeing": "BA", "caterpillar": "CAT",
    "pfizer": "PFE", "johnson & johnson": "JNJ", "johnson and johnson": "JNJ", "merck": "MRK",
    "eli lilly": "LLY", "lilly": "LLY", "unitedhealth": "UNH",
    "dbs": "D05.SI", "dbs bank": "D05.SI", "ocbc": "O39.SI", "uob": "U11.SI", "singtel": "Z74.SI",
    "singapore airlines": "C6L.SI", "sia": "C6L.SI", "capitaland": "9CI.SI", "keppel": "BN4.SI",
    "sgx": "S68.SI", "wilmar": "F34.SI",
}

# Display names used when Yahoo search is unavailable.
KNOWN_NAMES: Dict[str, str] = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation", "GOOGL": "Alphabet Inc. (Class A)",
    "GOOG": "Alphabet Inc. (Class C)", "META": "Meta Platforms, Inc.", "AMZN": "Amazon.com, Inc.",
    "NVDA": "NVIDIA Corporation", "TSLA": "Tesla, Inc.", "NFLX": "Netflix, Inc.", "MU": "Micron Technology, Inc.",
    "INTC": "Intel Corporation", "AMD": "Advanced Micro Devices, Inc.", "IBM": "International Business Machines",
    "ORCL": "Oracle Corporation", "CRM": "Salesforce, Inc.", "ADBE": "Adobe Inc.", "CSCO": "Cisco Systems, Inc.",
    "QCOM": "QUALCOMM Incorporated", "AVGO": "Broadcom Inc.", "TSM": "Taiwan Semiconductor Manufacturing (ADR)",
    "UBER": "Uber Technologies, Inc.", "ABNB": "Airbnb, Inc.", "PYPL": "PayPal Holdings, Inc.",
    "SHOP": "Shopify Inc.", "BABA": "Alibaba Group (ADR)", "SONY": "Sony Group Corporation (ADR)",
    "TM": "Toyota Motor Corporation (ADR)", "JPM": "JPMorgan Chase & Co.", "GS": "The Goldman Sachs Group, Inc.",
    "MS": "Morgan Stanley", "BAC": "Bank of America Corporation", "C": "Citigroup Inc.",
    "WFC": "Wells Fargo & Company", "V": "Visa Inc.", "MA": "Mastercard Incorporated",
    "AXP": "American Express Company", "BLK": "BlackRock, Inc.", "BRK-B": "Berkshire Hathaway Inc. (Class B)",
    "BRK-A": "Berkshire Hathaway Inc. (Class A)", "HSBC": "HSBC Holdings plc (ADR)", "WMT": "Walmart Inc.",
    "COST": "Costco Wholesale Corporation", "KO": "The Coca-Cola Company", "PEP": "PepsiCo, Inc.",
    "MCD": "McDonald's Corporation", "NKE": "NIKE, Inc.", "DIS": "The Walt Disney Company",
    "SBUX": "Starbucks Corporation", "PG": "The Procter & Gamble Company", "XOM": "Exxon Mobil Corporation",
    "CVX": "Chevron Corporation", "BA": "The Boeing Company", "CAT": "Caterpillar Inc.", "PFE": "Pfizer Inc.",
    "JNJ": "Johnson & Johnson", "MRK": "Merck & Co., Inc.", "LLY": "Eli Lilly and Company",
    "UNH": "UnitedHealth Group Incorporated", "D05.SI": "DBS Group Holdings Ltd", "O39.SI": "Oversea-Chinese Banking Corp",
    "U11.SI": "United Overseas Bank Ltd", "Z74.SI": "Singapore Telecommunications Ltd",
    "C6L.SI": "Singapore Airlines Ltd", "9CI.SI": "CapitaLand Investment Ltd", "BN4.SI": "Keppel Ltd",
    "S68.SI": "Singapore Exchange Ltd", "F34.SI": "Wilmar International Ltd",
}

# Other listings of the same company that a user may prefer (share classes).
ALTERNATIVE_LISTINGS: Dict[str, List[str]] = {"GOOGL": ["GOOG"], "BRK-B": ["BRK-A"]}


@dataclass(frozen=True)
class CompanyMatch:
    ticker: str
    name: str
    exchange: Optional[str] = None
    source: str = "search"  # "alias", "search" or "typed"

    @property
    def label(self) -> str:
        """e.g. 'NVIDIA Corporation (NVDA) · NASDAQ'"""
        return f"{self.name} ({self.ticker})" + (f" · {self.exchange}" if self.exchange else "")


@dataclass
class Resolution:
    """Result of resolving one or more typed entries."""

    chosen: List[CompanyMatch] = field(default_factory=list)  # best match per entry
    typed_as: Dict[str, str] = field(default_factory=dict)  # ticker -> what the user typed
    alternatives: Dict[str, List[CompanyMatch]] = field(default_factory=dict)  # ticker -> other matches
    not_found: List[Tuple[str, Optional[CompanyMatch]]] = field(default_factory=list)  # (typed, suggestion)
    over_limit: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Matching helpers
# --------------------------------------------------------------------------

def normalise_name(text: str) -> str:
    """'  The Coca-Cola Company ' -> 'coca-cola'; 'NVIDIA Corp.' -> 'nvidia'."""
    words = re.sub(r"[.,]", " ", (text or "").lower()).split()
    while len(words) > 1 and words[-1] in _SUFFIX_WORDS:
        words.pop()
    if len(words) > 1 and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def looks_like_ticker(text: str) -> bool:
    return bool(_TICKER_SHAPE.match(text.strip().upper()))


def _rank(quote: dict, query: str) -> Tuple[int, int]:
    symbol = str(quote.get("symbol", "")).upper()
    exchange = quote.get("exchange")
    if exchange in US_PRIMARY:
        tier = 0
    elif exchange in OVER_THE_COUNTER:
        tier = 2
    else:
        tier = 1
    return (0 if symbol == query.strip().upper() else 1, tier)


def matches_from_quotes(quotes: List[dict], query: str) -> List[CompanyMatch]:
    """Equities only, best first: exact symbol, then US primary, other primary, OTC."""
    equities = [q for q in quotes or [] if q.get("quoteType") == "EQUITY" and q.get("symbol")]
    ordered = sorted(enumerate(equities), key=lambda pair: (_rank(pair[1], query), pair[0]))
    matches: List[CompanyMatch] = []
    for _, quote in ordered:
        ticker = str(quote["symbol"]).upper()
        if any(m.ticker == ticker for m in matches):
            continue
        name = quote.get("longname") or quote.get("shortname") or KNOWN_NAMES.get(ticker) or ticker
        matches.append(CompanyMatch(ticker, name, quote.get("exchDisp") or quote.get("exchange"), "search"))
    return matches


def _safe_search(search: Optional[SearchFunction], query: str) -> Optional[List[dict]]:
    """None means Yahoo could not be searched (offline or error)."""
    if search is None:
        return None
    try:
        return search(query)
    except Exception:
        return None


def suggest_company(text: str) -> Optional[CompanyMatch]:
    """Closest well-known name, e.g. 'Gogle' -> Google (GOOGL)."""
    close = difflib.get_close_matches(normalise_name(text), list(COMPANY_TICKERS), n=1, cutoff=0.7)
    if not close:
        return None
    ticker = COMPANY_TICKERS[close[0]]
    return CompanyMatch(ticker, KNOWN_NAMES.get(ticker, close[0].title()), None, "alias")


# --------------------------------------------------------------------------
# Public functions
# --------------------------------------------------------------------------

def resolve_company(query: str, search: Optional[SearchFunction] = None) -> List[CompanyMatch]:
    """All plausible matches for one company name or ticker, best first.

    An empty list means nothing was found.
    """
    query = re.sub(r"\s+", " ", (query or "").strip())
    if not query:
        return []
    alias_ticker = COMPANY_TICKERS.get(normalise_name(query))
    quotes = _safe_search(search, alias_ticker or query)
    found = matches_from_quotes(quotes or [], alias_ticker or query)

    if alias_ticker:
        primary = next((m for m in found if m.ticker == alias_ticker), None)
        primary = CompanyMatch(alias_ticker, primary.name if primary else KNOWN_NAMES.get(alias_ticker, alias_ticker),
                               primary.exchange if primary else None, "alias")
        others = [CompanyMatch(t, KNOWN_NAMES.get(t, t), None, "alias") for t in ALTERNATIVE_LISTINGS.get(alias_ticker, [])]
        # Other companies Yahoo associates with the typed name (e.g. small firms also called "Meta").
        by_name = matches_from_quotes(_safe_search(search, query) or [], query) if search else []
        for match in by_name:
            if match.ticker != alias_ticker and all(o.ticker != match.ticker for o in others):
                others.append(match)
        return [primary] + others[:4]

    if found:
        return found[:5]
    suggestion = suggest_company(query)
    if suggestion is not None:
        if suggestion.ticker == query.upper():  # "nvda" is close to "nvidia" but is the ticker itself
            return [suggestion]
        return []  # most likely a misspelt company name ("Gogle"): offer the suggestion instead
    if looks_like_ticker(query):
        # Yahoo search unreachable or silent: accept a ticker-shaped entry as typed;
        # it is checked against Yahoo prices when the briefing is generated.
        ticker = query.upper()
        return [CompanyMatch(ticker, KNOWN_NAMES.get(ticker, ticker), None, "typed")]
    return []


def split_entries(text: str) -> List[str]:
    """Split on commas, semicolons, new lines and full stops followed by a space.
    Dots inside symbols such as D05.SI or 7203.T are kept."""
    text = re.sub(r"\.(\s+|$)", ",", text or "")
    text = re.sub(r"(^|\s)\.(?=\s|$)", ",", text)
    return [entry.strip() for entry in re.split(r"[,;\n]+", text) if entry.strip()]


def is_list(text: str) -> bool:
    return len(split_entries(text)) > 1


def resolve_entries(text: str, search: Optional[SearchFunction] = None,
                    already: Optional[List[str]] = None, limit: int = MAX_COMPANIES) -> Resolution:
    """Resolve a typed list ("Google, Apple . Meta" or "aapl msft") to the best match per entry."""
    result = Resolution()
    taken = list(already or [])
    entries = split_entries(text)
    if len(entries) == 1 and " " in entries[0] and not resolve_company(entries[0], search):
        entries = entries[0].split()  # "aapl msft nvda": a space-separated list of tickers
    for entry in entries:
        matches = resolve_company(entry, search)
        if not matches:
            result.not_found.append((entry, suggest_company(entry)))
            continue
        best = matches[0]
        if best.ticker in taken:
            continue
        if len(taken) >= limit:
            result.over_limit.append(best.ticker)
            continue
        taken.append(best.ticker)
        result.chosen.append(best)
        if entry.strip().upper() != best.ticker:
            result.typed_as[best.ticker] = entry
        if len(matches) > 1:
            result.alternatives[best.ticker] = matches[1:]
    return result
