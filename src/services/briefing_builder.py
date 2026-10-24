"""Assemble a complete Briefing from Yahoo data for several companies.

The fetch functions are passed in, so the app can supply cached versions and
tests can supply fakes. One failing ticker is recorded in failed_tickers and
does not stop the others.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List

import pandas as pd

from analytics.performance import align_prices, holding_period_returns, normalize_prices
from analytics.ratios import compute_ratios
from config import APP_VERSION, NEWS_ITEMS_PER_TICKER
from models.briefing import Briefing, CompanySnapshot
from services import yahoo


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_company_snapshot(ticker: str, closes: pd.Series, raw: dict, retrieved_at: str) -> CompanySnapshot:
    profile = yahoo.extract_profile(raw.get("info"), ticker)
    financials: Dict[str, Dict] = {}
    financials.update(yahoo.extract_statement_items(raw.get("income_statement"), yahoo.INCOME_ITEMS))
    financials.update(yahoo.extract_statement_items(raw.get("balance_sheet"), yahoo.BALANCE_ITEMS))
    financials.update(yahoo.extract_statement_items(raw.get("cash_flow"), yahoo.CASHFLOW_ITEMS))
    ratios, latest_fy, prior_fy = compute_ratios(financials)

    warnings = list(raw.get("warnings", []))
    if not financials:
        warnings.append("Yahoo returned no financial statements for this company.")
    news = yahoo.parse_news(raw.get("news"), ticker, limit=NEWS_ITEMS_PER_TICKER)
    if not news:
        warnings.append("Yahoo returned no recent news for this company.")

    return CompanySnapshot(
        ticker=ticker,
        name=profile["name"],
        currency=profile["currency"],
        financial_currency=profile["financial_currency"],
        retrieved_at=retrieved_at,
        source_name=yahoo.SOURCE_NAME,
        source_url=yahoo.quote_url(ticker),
        last_close=float(closes.iloc[-1]),
        last_close_date=closes.index[-1].strftime("%Y-%m-%d"),
        market_cap=profile["market_cap"],
        pe_ratio=profile["pe_ratio"],
        financials=financials,
        fiscal_year_end=latest_fy,
        prior_fiscal_year_end=prior_fy,
        ratios=ratios,
        ratings=yahoo.extract_latest_ratings(raw.get("recommendations")),
        news=news,
        warnings=warnings,
    )


def build_briefing(
    tickers: List[str],
    period_label: str,
    period_code: str,
    fetch_history: Callable[[str, str], pd.Series],
    fetch_company: Callable[[str], dict],
    on_progress: Callable[[str], None] = lambda message: None,
) -> Briefing:
    """Retrieve and combine data for every ticker into one Briefing."""
    created_at = utc_now_iso()
    companies: List[CompanySnapshot] = []
    prices: Dict[str, pd.Series] = {}
    failed: Dict[str, str] = {}

    for ticker in tickers:
        on_progress(f"Retrieving {ticker}…")
        try:
            closes = fetch_history(ticker, period_code)
        except Exception as exc:
            failed[ticker] = str(exc) or exc.__class__.__name__
            continue
        try:
            raw = fetch_company(ticker)
        except Exception as exc:
            raw = {"warnings": [f"Company details unavailable: {exc}"]}
        companies.append(build_company_snapshot(ticker, closes, raw, utc_now_iso()))
        prices[ticker] = closes

    aligned = align_prices(prices)
    normalized = normalize_prices(aligned)
    price_index = {
        ticker: {date.strftime("%Y-%m-%d"): round(float(value), 4) for date, value in normalized[ticker].items()}
        for ticker in normalized.columns
    }
    price_history = {
        ticker: {date.strftime("%Y-%m-%d"): round(float(value), 4) for date, value in aligned[ticker].items()}
        for ticker in normalized.columns
    }
    window = (
        [aligned.index[0].strftime("%Y-%m-%d"), aligned.index[-1].strftime("%Y-%m-%d")]
        if len(aligned) >= 2
        else None
    )

    return Briefing(
        briefing_id=str(uuid.uuid4()),
        created_at=created_at,
        analysis_period=period_label,
        tickers=list(tickers),
        companies=companies,
        price_index=price_index,
        price_history=price_history,
        holding_period_returns=holding_period_returns(aligned) if window else {},
        price_window=window,
        failed_tickers=failed,
        app_version=APP_VERSION,
    )
