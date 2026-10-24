"""Forgiving ticker input: names, separators, limits and suggestions."""

from __future__ import annotations

import pytest

from services.ticker_input import MAX_TICKERS, parse_ticker_input, suggest_ticker


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Google, Apple . Meta", ["GOOGL", "AAPL", "META"]),
        ("Apple. Meta.", ["AAPL", "META"]),
        (" aapl, MSFT ,aapl;mu  ", ["AAPL", "MSFT", "MU"]),
        ("aapl msft\nnvda", ["AAPL", "MSFT", "NVDA"]),
        ("bank of america apple", ["BAC", "AAPL"]),
        ("The Coca-Cola Company, Pepsico Inc.", ["KO", "PEP"]),
        ("Micron Technology Inc, nvidia", ["MU", "NVDA"]),
        ("DBS, OCBC", ["D05.SI", "O39.SI"]),
    ],
)
def test_names_and_separators(text, expected):
    assert parse_ticker_input(text).tickers == expected


def test_dots_inside_symbols_are_kept():
    assert parse_ticker_input("D05.SI, 7203.T, BRK-B").tickers == ["D05.SI", "7203.T", "BRK-B"]


def test_mapped_names_are_reported_but_plain_tickers_are_not():
    parsed = parse_ticker_input("Google, MSFT")
    assert parsed.mapped == [("Google", "GOOGL")]


def test_invalid_entries_and_duplicates():
    parsed = parse_ticker_input("$$$, AAPL, AAPL, apple")
    assert parsed.tickers == ["AAPL"] and parsed.rejected == ["$$$"]


def test_limit_on_number_of_companies():
    parsed = parse_ticker_input("a, b, c, d, e, f, g, h")
    assert len(parsed.tickers) == MAX_TICKERS and parsed.truncated == ["G", "H"]


def test_suggestions():
    assert suggest_ticker("GOOGLE") == ["GOOGL"]
    assert suggest_ticker("microsft") == ["MSFT"]
    assert suggest_ticker("XYZQ") == []
