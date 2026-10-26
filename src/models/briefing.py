"""Shared data structures for a Nimbus company briefing.

A Briefing is the complete result of one "Generate briefing" run plus the RM
note added before saving. It converts to and from plain dictionaries so it can
be saved as a JSON snapshot and reopened later exactly as it was.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

SCHEMA_VERSION = 3  # 2: price_history; 3: news thumbnails, analyst view, earnings, saved articles
ANALYSIS_TYPE = "company_briefing"


@dataclass
class NewsItem:
    ticker: str
    headline: str
    summary: Optional[str]
    publisher: Optional[str]
    published_at: Optional[str]  # ISO 8601 date-time from the source, or None
    source_url: Optional[str]
    thumbnail_url: Optional[str] = None


@dataclass
class CompanySnapshot:
    """Everything retrieved for one ticker at one point in time."""

    ticker: str
    name: str
    currency: Optional[str]  # trading currency: price and market cap
    financial_currency: Optional[str]  # reporting currency: statement figures
    retrieved_at: str  # ISO 8601 UTC time the data was fetched
    source_name: str
    source_url: str
    last_close: Optional[float] = None
    last_close_date: Optional[str] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    # Line item -> {fiscal year end (YYYY-MM-DD) -> value}
    financials: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    fiscal_year_end: Optional[str] = None  # latest fiscal year used for ratios
    prior_fiscal_year_end: Optional[str] = None
    # Ratio name -> value (fractions, e.g. 0.12 means 12%); None means N/A
    ratios: Dict[str, Optional[float]] = field(default_factory=dict)
    # Latest analyst recommendation counts, e.g. {"period": "0m", "strongBuy": 9, ...}
    ratings: Optional[Dict[str, object]] = None
    news: List[NewsItem] = field(default_factory=list)
    # How the news was obtained: {"status": "ok"|"empty"|"error", "source", "message", "skipped"}
    news_status: Optional[Dict[str, object]] = None
    # Analyst consensus: recommendation, analysts, target_mean/high/low, upside (fraction)
    analyst: Optional[Dict[str, object]] = None
    # Earnings: next_date, next_eps_estimate, last_date, last_eps_estimate, last_eps_actual,
    # last_surprise (fraction), last_result ("beat" / "miss" / "in line")
    earnings: Optional[Dict[str, object]] = None
    warnings: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CompanySnapshot":
        values = dict(data)
        values["news"] = [NewsItem(**item) for item in data.get("news", [])]
        return cls(**values)


@dataclass
class RmNote:
    client_reference: str
    meeting_date: Optional[str]  # YYYY-MM-DD
    discussion_summary: str
    client_priorities: str
    follow_up_actions: str
    next_review_date: Optional[str]  # YYYY-MM-DD
    free_text: str
    created_at: str  # ISO 8601 UTC
    # News articles the RM chose to keep with this note (ticker, headline, publisher, published_at, source_url)
    saved_articles: List[Dict[str, Optional[str]]] = field(default_factory=list)


@dataclass
class Briefing:
    briefing_id: str
    created_at: str  # ISO 8601 UTC, when the briefing was generated
    analysis_period: str  # label shown to the user, e.g. "1 year"
    tickers: List[str]
    companies: List[CompanySnapshot]
    # Normalized share prices (first common date = 100): ticker -> {date: value}
    price_index: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Adjusted closing prices on the same common dates: ticker -> {date: price}
    price_history: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Holding-period return over the common date range: ticker -> fraction
    holding_period_returns: Dict[str, Optional[float]] = field(default_factory=dict)
    price_window: Optional[List[str]] = None  # [first date, last date]
    failed_tickers: Dict[str, str] = field(default_factory=dict)  # ticker -> reason
    note: Optional[RmNote] = None
    saved_at: Optional[str] = None
    analysis_type: str = ANALYSIS_TYPE
    schema_version: int = SCHEMA_VERSION
    app_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Briefing":
        values = dict(data)
        values["companies"] = [CompanySnapshot.from_dict(c) for c in data.get("companies", [])]
        values["note"] = RmNote(**data["note"]) if data.get("note") else None
        return cls(**values)

    @property
    def successful_tickers(self) -> List[str]:
        return [company.ticker for company in self.companies]
