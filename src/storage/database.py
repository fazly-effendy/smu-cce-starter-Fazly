"""Briefing metadata and RM notes in a SQL database (Feature 5).

Lesson 8 design: the briefing file stays on disk (EBS on AWS); the database
stores metadata about each file so users search the metadata with SQL instead
of guessing filenames. Locally this is SQLite; on AWS the same code points at
Amazon RDS for MySQL by changing NIMBUS_DATABASE_URL only.

Tables
------
briefings         one row per saved briefing: when, analysis type, period,
                  client reference, and the snapshot filenames
briefing_tickers  one row per ticker in a briefing (lets SQL find every
                  briefing that includes, say, MU)
rm_notes          the RM note, linked to its briefing by briefing_id

The lesson's example table (ticker, analysis_type, date, filename) is the
join of briefings and briefing_tickers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from config import database_url, to_local
from models.briefing import Briefing

metadata = MetaData()

briefings = Table(
    "briefings",
    metadata,
    Column("briefing_id", String(36), primary_key=True),
    Column("created_at", DateTime, nullable=False),  # when the data was retrieved (UTC)
    Column("saved_at", DateTime, nullable=False),  # when the user saved it (UTC)
    Column("analysis_date", Date, nullable=False, index=True),  # local save date (NIMBUS_TIMEZONE), for search
    Column("analysis_type", String(32), nullable=False, index=True),
    Column("analysis_period", String(32), nullable=False),
    Column("client_reference", String(200), nullable=True, index=True),
    Column("tickers", String(255), nullable=False),  # display copy, e.g. "AAPL, MSFT"
    Column("filename", String(255), nullable=False),  # Markdown file in analyses-data/
    Column("json_filename", String(255), nullable=False),  # JSON snapshot used to reopen
    Column("schema_version", Integer, nullable=False),
    Column("app_version", String(16), nullable=False),
)

briefing_tickers = Table(
    "briefing_tickers",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "briefing_id",
        String(36),
        ForeignKey("briefings.briefing_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ticker", String(16), nullable=False, index=True),
    UniqueConstraint("briefing_id", "ticker", name="uq_briefing_ticker"),
)

rm_notes = Table(
    "rm_notes",
    metadata,
    Column("note_id", Integer, primary_key=True, autoincrement=True),
    Column(
        "briefing_id",
        String(36),
        ForeignKey("briefings.briefing_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("meeting_date", Date, nullable=True),
    Column("next_review_date", Date, nullable=True),
    Column("discussion_summary", Text, nullable=True),
    Column("client_priorities", Text, nullable=True),
    Column("follow_up_actions", Text, nullable=True),
    Column("free_text", Text, nullable=True),
    Column("created_at", DateTime, nullable=False),
)

_engines: Dict[str, Engine] = {}


def get_engine(url: Optional[str] = None) -> Engine:
    """One engine per database URL; tables are created on first use."""
    url = url or database_url()
    if url not in _engines:
        engine = create_engine(url, pool_pre_ping=True, future=True)
        if engine.dialect.name == "sqlite":
            @event.listens_for(engine, "connect")
            def _enable_foreign_keys(connection, _record):  # SQLite needs this per connection
                connection.execute("PRAGMA foreign_keys=ON")
        metadata.create_all(engine)
        _engines[url] = engine
    return _engines[url]


def _parse_dt(value: str) -> datetime:
    """ISO 8601 UTC string -> naive UTC datetime (MySQL DATETIME has no time zone)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _parse_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def briefing_exists(briefing_id: str, engine: Optional[Engine] = None) -> bool:
    engine = engine or get_engine()
    with engine.connect() as connection:
        found = connection.execute(
            select(briefings.c.briefing_id).where(briefings.c.briefing_id == briefing_id)
        ).first()
    return found is not None


def insert_briefing(
    briefing: Briefing, filename: str, json_filename: str, engine: Optional[Engine] = None
) -> bool:
    """Insert the briefing, its tickers and its note in one transaction.

    Returns False (and changes nothing) if this briefing_id is already saved,
    which makes saving safe to repeat.
    """
    engine = engine or get_engine()
    note = briefing.note
    try:
        with engine.begin() as connection:  # commits on success, rolls back on any error
            connection.execute(
                briefings.insert().values(
                    briefing_id=briefing.briefing_id,
                    created_at=_parse_dt(briefing.created_at),
                    saved_at=_parse_dt(briefing.saved_at or briefing.created_at),
                    analysis_date=to_local(_parse_dt(briefing.saved_at or briefing.created_at)).date(),
                    analysis_type=briefing.analysis_type,
                    analysis_period=briefing.analysis_period,
                    client_reference=(note.client_reference.strip() if note and note.client_reference else None),
                    tickers=", ".join(briefing.successful_tickers)[:255],
                    filename=filename,
                    json_filename=json_filename,
                    schema_version=briefing.schema_version,
                    app_version=briefing.app_version,
                )
            )
            connection.execute(
                briefing_tickers.insert(),
                [{"briefing_id": briefing.briefing_id, "ticker": t} for t in briefing.successful_tickers],
            )
            if note:
                connection.execute(
                    rm_notes.insert().values(
                        briefing_id=briefing.briefing_id,
                        meeting_date=_parse_date(note.meeting_date),
                        next_review_date=_parse_date(note.next_review_date),
                        discussion_summary=note.discussion_summary,
                        client_priorities=note.client_priorities,
                        follow_up_actions=note.follow_up_actions,
                        free_text=note.free_text,
                        created_at=_parse_dt(note.created_at),
                    )
                )
    except IntegrityError:
        if briefing_exists(briefing.briefing_id, engine):
            return False
        raise
    return True


def search_briefings(
    ticker: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    client_reference: Optional[str] = None,
    analysis_type: Optional[str] = None,
    limit: int = 200,
    engine: Optional[Engine] = None,
) -> List[dict]:
    """Find saved briefings by metadata, newest first.

    Equivalent SQL for a ticker search:
        SELECT b.* FROM briefings b
        WHERE b.briefing_id IN (SELECT briefing_id FROM briefing_tickers WHERE ticker = 'MU')
        ORDER BY b.saved_at DESC;
    """
    engine = engine or get_engine()
    query = select(briefings)
    if ticker and ticker.strip():
        matching = select(briefing_tickers.c.briefing_id).where(
            briefing_tickers.c.ticker == ticker.strip().upper()
        )
        query = query.where(briefings.c.briefing_id.in_(matching))
    if date_from:
        query = query.where(briefings.c.analysis_date >= date_from)
    if date_to:
        query = query.where(briefings.c.analysis_date <= date_to)
    if client_reference and client_reference.strip():
        pattern = f"%{client_reference.strip().lower()}%"
        query = query.where(func.lower(briefings.c.client_reference).like(pattern))
    if analysis_type:
        query = query.where(briefings.c.analysis_type == analysis_type)
    query = query.order_by(briefings.c.saved_at.desc()).limit(limit)
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(query)]


def get_note(briefing_id: str, engine: Optional[Engine] = None) -> Optional[dict]:
    engine = engine or get_engine()
    with engine.connect() as connection:
        row = connection.execute(select(rm_notes).where(rm_notes.c.briefing_id == briefing_id)).first()
    return dict(row._mapping) if row else None


def count_rows(engine: Optional[Engine] = None) -> Dict[str, int]:
    """Row counts per table (shown in the History tab for verification)."""
    engine = engine or get_engine()
    with engine.connect() as connection:
        return {
            table.name: connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (briefings, briefing_tickers, rm_notes)
        }
