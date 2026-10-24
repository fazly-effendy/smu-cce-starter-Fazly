"""Turn what an RM types into Yahoo Finance ticker symbols.

Accepts tickers or common company names, separated by commas, semicolons,
new lines, spaces or a full stop followed by a space:

    "Google, Apple . Meta"  ->  GOOGL, AAPL, META
    "aapl msft; dbs"        ->  AAPL, MSFT, D05.SI

A dot inside a symbol is kept, because exchange suffixes use it (D05.SI on
SGX, 7203.T in Tokyo). Company names are matched against a short list of
well-known names; anything else is treated as a ticker and checked against
Yahoo when the briefing is generated.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

MAX_TICKERS = 6

_TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,14}$")
_SUFFIX_WORDS = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
                 "holdings", "group", "the", "sa", "ag", "nv"}

# Common company names -> Yahoo Finance tickers. Keys are lower case.
COMPANY_TICKERS: Dict[str, str] = {
    # US technology
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL", "meta": "META",
    "facebook": "META", "meta platforms": "META", "amazon": "AMZN", "nvidia": "NVDA", "tesla": "TSLA",
    "netflix": "NFLX", "micron": "MU", "micron technology": "MU", "intel": "INTC", "amd": "AMD",
    "advanced micro devices": "AMD", "ibm": "IBM", "oracle": "ORCL", "salesforce": "CRM", "adobe": "ADBE",
    "cisco": "CSCO", "qualcomm": "QCOM", "broadcom": "AVGO", "tsmc": "TSM",
    "taiwan semiconductor": "TSM", "uber": "UBER", "airbnb": "ABNB", "paypal": "PYPL", "shopify": "SHOP",
    "alibaba": "BABA", "sony": "SONY", "toyota": "TM",
    # US financials
    "jpmorgan": "JPM", "jp morgan": "JPM", "jpmorgan chase": "JPM", "goldman sachs": "GS", "goldman": "GS",
    "morgan stanley": "MS", "bank of america": "BAC", "citigroup": "C", "citi": "C", "wells fargo": "WFC",
    "visa": "V", "mastercard": "MA", "american express": "AXP", "amex": "AXP", "blackrock": "BLK",
    "berkshire hathaway": "BRK-B", "berkshire": "BRK-B", "hsbc": "HSBC",
    # US consumer, industrial, energy, health
    "walmart": "WMT", "costco": "COST", "coca-cola": "KO", "coca cola": "KO", "coke": "KO", "pepsi": "PEP",
    "pepsico": "PEP", "mcdonalds": "MCD", "mcdonald's": "MCD", "nike": "NKE", "disney": "DIS",
    "starbucks": "SBUX", "procter & gamble": "PG", "procter and gamble": "PG", "exxon": "XOM",
    "exxonmobil": "XOM", "exxon mobil": "XOM", "chevron": "CVX", "boeing": "BA", "caterpillar": "CAT",
    "pfizer": "PFE", "johnson & johnson": "JNJ", "johnson and johnson": "JNJ", "merck": "MRK",
    "eli lilly": "LLY", "lilly": "LLY", "unitedhealth": "UNH",
    # Singapore (SGX listings on Yahoo end in .SI)
    "dbs": "D05.SI", "dbs bank": "D05.SI", "ocbc": "O39.SI", "uob": "U11.SI", "singtel": "Z74.SI",
    "singapore airlines": "C6L.SI", "sia": "C6L.SI", "capitaland": "9CI.SI", "keppel": "BN4.SI",
    "sgx": "S68.SI", "wilmar": "F34.SI",
}


@dataclass
class ParsedInput:
    tickers: List[str] = field(default_factory=list)
    mapped: List[Tuple[str, str]] = field(default_factory=list)  # (what was typed, ticker used)
    rejected: List[str] = field(default_factory=list)
    truncated: List[str] = field(default_factory=list)  # valid but over MAX_TICKERS


def _normalise_name(text: str) -> str:
    words = re.sub(r"[.,]", " ", text.lower()).split()
    while words and words[-1] in _SUFFIX_WORDS:
        words.pop()
    if words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def _split_entries(text: str) -> List[str]:
    text = re.sub(r"\.(\s+|$)", ",", text or "")  # "Apple. Meta" / "Apple . Meta" / trailing "."
    text = re.sub(r"(^|\s)\.(?=\s|$)", ",", text)  # a dot standing on its own
    return [entry.strip() for entry in re.split(r"[,;\n]+", text) if entry.strip()]


def _resolve_entry(entry: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Return ([(typed, ticker), ...], [rejected pieces]) for one comma-separated entry."""
    whole = _normalise_name(entry)
    if whole in COMPANY_TICKERS:
        return [(entry, COMPANY_TICKERS[whole])], []
    tokens = entry.split()
    found: List[Tuple[str, str]] = []
    rejected: List[str] = []
    i = 0
    while i < len(tokens):
        for size in (3, 2, 1):  # longest company name first, e.g. "bank of america"
            piece = " ".join(tokens[i:i + size])
            name = _normalise_name(piece)
            if size <= len(tokens) - i and name in COMPANY_TICKERS:
                found.append((piece, COMPANY_TICKERS[name]))
                i += size
                break
        else:
            symbol = tokens[i].strip(".").upper()
            if _TICKER_PATTERN.match(symbol):
                found.append((tokens[i], symbol))
            elif tokens[i].strip("."):
                rejected.append(tokens[i])
            i += 1
    return found, rejected


def parse_ticker_input(text: str, max_tickers: int = MAX_TICKERS) -> ParsedInput:
    result = ParsedInput()
    for entry in _split_entries(text):
        found, rejected = _resolve_entry(entry)
        result.rejected.extend(rejected)
        for typed, ticker in found:
            if ticker in result.tickers or ticker in result.truncated:
                continue
            if len(result.tickers) >= max_tickers:
                result.truncated.append(ticker)
                continue
            result.tickers.append(ticker)
            if typed.strip(".").upper() != ticker:
                result.mapped.append((typed, ticker))
    return result


def suggest_ticker(text: str) -> List[str]:
    """Suggestions for an entry Yahoo did not recognise, e.g. 'GOOGLE' -> ['GOOGL']."""
    name = _normalise_name(text)
    if name in COMPANY_TICKERS:
        return [COMPANY_TICKERS[name]]
    close = difflib.get_close_matches(name, list(COMPANY_TICKERS), n=2, cutoff=0.75)
    suggestions: List[str] = []
    for match in close:
        if COMPANY_TICKERS[match] not in suggestions:
            suggestions.append(COMPANY_TICKERS[match])
    return suggestions
