"""Company name and ticker resolution (services/company_lookup.py)."""

from __future__ import annotations

import pytest

import fake_yahoo
from services import yahoo
from services.company_lookup import (
    MAX_COMPANIES,
    matches_from_quotes,
    normalise_name,
    resolve_company,
    resolve_entries,
    split_entries,
    suggest_company,
)

search = yahoo.search_quotes  # patched to the fake Yahoo by conftest


def tickers(matches):
    return [m.ticker for m in matches]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("  NVIDIA Corp. ", "nvidia"),
        ("The Coca-Cola Company", "coca-cola"),
        ("Meta Platforms Inc", "meta platforms"),
        ("Alphabet Inc Class A", "alphabet"),
    ],
)
def test_normalise_name_ignores_case_spaces_and_suffixes(text, expected):
    assert normalise_name(text) == expected


def test_alias_names_resolve_offline():
    assert tickers(resolve_company("Google", None))[0] == "GOOGL"
    assert tickers(resolve_company("nvidia corporation", None)) == ["NVDA"]
    assert tickers(resolve_company("DBS", None)) == ["D05.SI"]


def test_ambiguous_name_offers_other_listings():
    matches = resolve_company("Google", search)
    assert tickers(matches) == ["GOOGL", "GOOG"]
    assert matches[0].source == "alias"


def test_alias_also_lists_other_companies_with_the_same_name():
    matches = resolve_company("Meta", search)
    assert tickers(matches) == ["META", "MMAT"]
    assert matches[0].exchange == "NASDAQ"  # exchange taken from Yahoo search


def test_search_fallback_prefers_us_primary_listing_and_equities_only():
    matches = resolve_company("palantir", search)
    assert tickers(matches) == ["PLTR", "PTX.F"]  # Frankfurt listing second, ETF dropped
    assert matches[0].label == "Palantir Technologies Inc. (PLTR) · NASDAQ"


def test_partial_name_search():
    assert resolve_company("nvid", search)[0].label == "NVIDIA Corporation (NVDA) · NASDAQ"


def test_otc_listings_rank_below_primary_exchanges():
    quotes = fake_yahoo.SEARCH_RESULTS["dbs group"]
    assert tickers(matches_from_quotes(quotes, "dbs group")) == ["D05.SI", "DBSDY"]


def test_exact_symbol_ranks_first():
    quotes = [
        {"symbol": "AAPL.MX", "quoteType": "EQUITY", "exchange": "MEX"},
        {"symbol": "AAPL", "quoteType": "EQUITY", "exchange": "NMS"},
    ]
    assert tickers(matches_from_quotes(quotes, "aapl"))[0] == "AAPL"


def test_tickers_are_accepted_when_search_is_offline():
    fake_yahoo.SEARCH_ONLINE = False
    assert tickers(resolve_company("MU", search)) == ["MU"]
    assert tickers(resolve_company("D05.SI", search)) == ["D05.SI"]
    assert tickers(resolve_company("nvda", search)) == ["NVDA"]


def test_misspelt_name_gives_suggestion_not_a_fake_ticker():
    assert resolve_company("Gogle", search) == []
    assert suggest_company("Gogle").ticker == "GOOGL"
    assert suggest_company("Microsft").ticker == "MSFT"
    assert suggest_company("xyzzy") is None


def test_split_entries_keeps_dots_inside_symbols():
    assert split_entries("Google, Apple . Meta") == ["Google", "Apple", "Meta"]
    assert split_entries("Apple. Meta.") == ["Apple", "Meta"]
    assert split_entries("D05.SI; 7203.T\nBRK-B") == ["D05.SI", "7203.T", "BRK-B"]


def test_resolve_list_with_names_tickers_and_duplicates():
    result = resolve_entries(" aapl, MSFT ,aapl; Google . Meta", search)
    assert tickers(result.chosen) == ["AAPL", "MSFT", "GOOGL", "META"]
    assert result.typed_as == {"GOOGL": "Google"}
    assert tickers(result.alternatives["GOOGL"]) == ["GOOG"]


def test_space_separated_tickers_and_multi_word_names():
    assert tickers(resolve_entries("aapl msft nvda", search).chosen) == ["AAPL", "MSFT", "NVDA"]
    assert tickers(resolve_entries("bank of america", search).chosen) == ["BAC"]


def test_not_found_and_limit():
    result = resolve_entries("Gogle, MSFT", search)
    assert tickers(result.chosen) == ["MSFT"]
    assert result.not_found[0][0] == "Gogle" and result.not_found[0][1].ticker == "GOOGL"
    full = resolve_entries("a, b, c, d, e, f, g", search, already=["AAPL"])
    assert len(full.chosen) == MAX_COMPANIES - 1 and full.over_limit == ["F", "G"]
