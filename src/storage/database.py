"""Client-discussion records in a SQL database (Features 3, 4 and 5).

Design (instructor feedback, 27 Oct 2026, building on Lesson 8): every saved
client discussion is stored in the database: the client, the discussion and,
for each company discussed, the values observed at that time. Users search by
client, by company and by date. Locally this is SQLite; on AWS the same code
uses Amazon RDS for MySQL. Only NIMBUS_DATABASE_URL changes.

Tables
------
clients               one row per client (client_id typed by the RM, optional name)
discussions           one row per saved discussion; one client has many discussions.
                      Holds the RM's notes and the complete snapshot (JSON) used to
                      reopen it, so any app server can reopen any discussion.
discussion_companies  one row per company in a discussion; one discussion has many
                      companies. Each row keeps the stock price and ratios as they were
                      at the time of the discussion.

The readable Markdown copy of each discussion is also written to disk (EBS on
AWS, Lesson 7); its filename is stored in discussions.filename.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    or_,
    select,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from config import database_url, to_local
from models.briefing import Briefing

metadata = MetaData()

# Snapshots are typically 50-200 KB: MySQL's TEXT holds only 64 KB, MEDIUMTEXT 16 MB.
# Numbers use DOUBLE: MySQL's FLOAT is single precision (about 7 digits), so a saved price
# or ratio would not read back exactly as saved.
LongText = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")

CLIENT_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")

clients = Table(
    "clients",
    metadata,
    Column("client_id", String(32), primary_key=True),
    Column("client_name", String(200), nullable=True),
    Column("created_at", DateTime, nullable=False),
)

discussions = Table(
    "discussions",
    metadata,
    Column("discussion_id", String(36), primary_key=True),
    Column("client_id", String(32), ForeignKey("clients.client_id"), nullable=False, index=True),
    Column("discussion_date", Date, nullable=False, index=True),  # local date of the meeting
    Column("created_at", DateTime, nullable=False),  # when it was saved (UTC)
    Column("data_retrieved_at", DateTime, nullable=False),  # when Yahoo was called (UTC)
    Column("comparison_period", String(32), nullable=False),  # e.g. "1 year"
    Column("tickers", String(255), nullable=False),  # display copy, e.g. "AAPL, MSFT"
    Column("client_interests", Text, nullable=False),
    Column("notes", Text, nullable=True),  # discussion summary
    Column("follow_up_actions", Text, nullable=True),
    Column("next_review_date", Date, nullable=True),
    Column("other_notes", Text, nullable=True),
    Column("filename", String(255), nullable=False),  # Markdown copy on disk / EBS
    Column("snapshot_json", LongText, nullable=False),  # complete snapshot used to reopen
    Column("schema_version", Integer, nullable=False),
    Column("app_version", String(16), nullable=False),
)

discussion_companies = Table(
    "discussion_companies",
    metadata,
    Column("discussion_id", String(36), ForeignKey("discussions.discussion_id", ondelete="CASCADE"),
           nullable=False),
    Column("ticker", String(16), nullable=False, index=True),
    Column("company_name", String(200), nullable=True, index=True),
    Column("stock_price", Double, nullable=True),  # last close at the time of the discussion
    Column("price_date", Date, nullable=True),  # date of that close (observation date)
    Column("currency", String(8), nullable=True),
    Column("revenue_growth", Double, nullable=True),  # fractions: 0.12 = 12%
    Column("net_margin", Double, nullable=True),
    Column("operating_margin", Double, nullable=True),
    Column("debt_to_equity", Double, nullable=True),  # multiple: 0.45 = 0.45x
    Column("fiscal_year_end", Date, nullable=True),  # year the ratios refer to
    Column("source", String(100), nullable=False),
    Column("retrieved_at", DateTime, nullable=False),
    PrimaryKeyConstraint("discussion_id", "ticker", name="pk_discussion_company"),
)

_engines: Dict[str, Engine] = {}

# Connections per app server to MySQL (RDS): 5 kept open, up to 5 more when busy. With
# several servers (scaling), the total stays well under what a db.t3.micro allows.
POOL_SIZE = 5
MAX_OVERFLOW = 5
POOL_RECYCLE_SECONDS = 1800  # replace idle connections before MySQL or the network drops them


def engine_options(url: str) -> dict:
    """Connection settings: a capped, self-healing pool for MySQL; defaults for SQLite."""
    options = {"pool_pre_ping": True, "future": True}  # pre-ping: test a connection before use
    if not url.startswith("sqlite"):
        options.update(pool_size=POOL_SIZE, max_overflow=MAX_OVERFLOW, pool_recycle=POOL_RECYCLE_SECONDS)
    return options


def get_engine(url: Optional[str] = None) -> Engine:
    """One engine per database URL; tables are created on first use."""
    url = url or database_url()
    if url not in _engines:
        engine = create_engine(url, **engine_options(url))
        if engine.dialect.name == "sqlite":
            @event.listens_for(engine, "connect")
            def _enable_foreign_keys(connection, _record):  # SQLite needs this per connection
                connection.execute("PRAGMA foreign_keys=ON")
        try:
            metadata.create_all(engine)
        except Exception:
            # Two new servers starting together can both try to create the tables; the one
            # that loses sees "already exists". Check again: this time they are there.
            metadata.create_all(engine)
        _engines[url] = engine
    return _engines[url]


def normalise_client_id(value: Optional[str]) -> str:
    """"c-1001 " -> "C-1001". Raises ValueError if it is not a valid client ID."""
    client_id = (value or "").strip().upper()
    if not CLIENT_ID_PATTERN.match(client_id):
        raise ValueError("A client ID is 1–32 letters, digits, - or _, starting with a letter or digit, "
                         "e.g. C-1001.")
    return client_id


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """ISO 8601 UTC string -> naive UTC datetime (MySQL DATETIME has no time zone)."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _parse_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value[:10]) if value else None


def discussion_exists(discussion_id: str, engine: Optional[Engine] = None) -> bool:
    engine = engine or get_engine()
    with engine.connect() as connection:
        found = connection.execute(
            select(discussions.c.discussion_id).where(discussions.c.discussion_id == discussion_id)
        ).first()
    return found is not None


def _ensure_client(connection, client_id: str, client_name: Optional[str], now: datetime) -> None:
    """Create the client on first use; fill in the name if it was not known before."""
    row = connection.execute(select(clients).where(clients.c.client_id == client_id)).first()
    name = (client_name or "").strip() or None
    if row is None:
        connection.execute(clients.insert().values(client_id=client_id, client_name=name, created_at=now))
    elif name and not row.client_name:
        connection.execute(clients.update().where(clients.c.client_id == client_id).values(client_name=name))


def insert_discussion(briefing: Briefing, filename: str, engine: Optional[Engine] = None) -> bool:
    """Insert the client (if new), the discussion and one row per company, in one transaction.

    Returns False (and changes nothing) if this discussion is already saved, which makes
    saving safe to repeat. The briefing must carry its note (client ID, date, interests).
    """
    engine = engine or get_engine()
    note = briefing.note
    if note is None:
        raise ValueError("A discussion needs its note (client ID, discussion date, client interests).")
    client_id = normalise_client_id(note.client_id)
    if not (note.client_interests or "").strip():
        raise ValueError("Notes about the client's interests are required.")
    saved_at = _parse_dt(briefing.saved_at or briefing.created_at)
    retrieved = [c.retrieved_at for c in briefing.companies if c.retrieved_at] or [briefing.created_at]
    # Up to two attempts: if another app server creates the same new client at the same moment,
    # the first attempt fails on the duplicate client and is rolled back completely; the
    # second finds the client and links the discussion to it.
    try:
        _insert_once(engine, briefing, client_id, note, saved_at, retrieved, filename)
    except IntegrityError:
        if discussion_exists(briefing.briefing_id, engine):
            return False  # already saved (e.g. a repeated click)
        _insert_once(engine, briefing, client_id, note, saved_at, retrieved, filename)  # second attempt
    return True


def _insert_once(engine: Engine, briefing: Briefing, client_id: str, note, saved_at: datetime,
                 retrieved: List[str], filename: str) -> None:
    """One transaction: the client (if new), the discussion and its company rows."""
    with engine.begin() as connection:  # commits on success, rolls back on any error
        _ensure_client(connection, client_id, note.client_name, saved_at)
        connection.execute(discussions.insert().values(
            discussion_id=briefing.briefing_id,
            client_id=client_id,
            discussion_date=_parse_date(note.discussion_date) or to_local(saved_at).date(),
            created_at=saved_at,
            data_retrieved_at=_parse_dt(min(retrieved)),
            comparison_period=briefing.analysis_period,
            tickers=", ".join(briefing.successful_tickers)[:255],
            client_interests=note.client_interests.strip(),
            notes=(note.notes or "").strip() or None,
            follow_up_actions=(note.follow_up_actions or "").strip() or None,
            next_review_date=_parse_date(note.next_review_date),
            other_notes=(note.free_text or "").strip() or None,
            filename=filename,
            snapshot_json=json.dumps(briefing.to_dict(), ensure_ascii=False),
            schema_version=briefing.schema_version,
            app_version=briefing.app_version,
        ))
        connection.execute(discussion_companies.insert(), [
            {
                "discussion_id": briefing.briefing_id,
                "ticker": c.ticker,
                "company_name": (c.name or c.ticker)[:200],
                "stock_price": c.last_close,
                "price_date": _parse_date(c.last_close_date),
                "currency": c.currency,
                "revenue_growth": c.ratios.get("revenue_growth"),
                "net_margin": c.ratios.get("net_margin"),
                "operating_margin": c.ratios.get("operating_margin"),
                "debt_to_equity": c.ratios.get("debt_to_equity"),
                "fiscal_year_end": _parse_date(c.fiscal_year_end),
                "source": c.source_name[:100],
                "retrieved_at": _parse_dt(c.retrieved_at),
            }
            for c in briefing.companies
        ])


def search_discussions(
    client_id: Optional[str] = None,
    company: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 200,
    engine: Optional[Engine] = None,
) -> List[dict]:
    """Find saved discussions by client, company (ticker or name) and discussion date, newest first.

    Equivalent SQL for "every discussion with client C-1001 that included NVIDIA":
        SELECT d.*, c.client_name FROM discussions d JOIN clients c ON c.client_id = d.client_id
        WHERE d.client_id = 'C-1001'
          AND d.discussion_id IN (SELECT discussion_id FROM discussion_companies
                                  WHERE ticker = 'NVIDIA' OR LOWER(company_name) LIKE '%nvidia%')
        ORDER BY d.discussion_date DESC, d.created_at DESC;
    """
    engine = engine or get_engine()
    columns = [c for c in discussions.c if c.name != "snapshot_json"]  # the snapshot is only loaded to reopen
    query = select(*columns, clients.c.client_name).join(clients, clients.c.client_id == discussions.c.client_id)
    if client_id and client_id.strip():
        query = query.where(discussions.c.client_id == client_id.strip().upper())
    if company and company.strip():
        text = company.strip()
        matching = select(discussion_companies.c.discussion_id).where(or_(
            discussion_companies.c.ticker == text.upper(),
            func.lower(discussion_companies.c.company_name).like(f"%{text.lower()}%"),
        ))
        query = query.where(discussions.c.discussion_id.in_(matching))
    if date_from:
        query = query.where(discussions.c.discussion_date >= date_from)
    if date_to:
        query = query.where(discussions.c.discussion_date <= date_to)
    query = query.order_by(discussions.c.discussion_date.desc(), discussions.c.created_at.desc()).limit(limit)
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(query)]


def get_discussion(discussion_id: str, engine: Optional[Engine] = None) -> Optional[dict]:
    """The discussion row (including snapshot_json) with the client's name, or None."""
    engine = engine or get_engine()
    query = (select(discussions, clients.c.client_name)
             .join(clients, clients.c.client_id == discussions.c.client_id)
             .where(discussions.c.discussion_id == discussion_id))
    with engine.connect() as connection:
        row = connection.execute(query).first()
    return dict(row._mapping) if row else None


def get_companies(discussion_id: str, engine: Optional[Engine] = None) -> List[dict]:
    """The per-company rows saved with a discussion (values at the time of the discussion)."""
    engine = engine or get_engine()
    query = (select(discussion_companies).where(discussion_companies.c.discussion_id == discussion_id)
             .order_by(discussion_companies.c.ticker))
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(query)]


def list_clients(engine: Optional[Engine] = None) -> List[dict]:
    """Every client, with the number of saved discussions, alphabetical by ID."""
    engine = engine or get_engine()
    query = (select(clients.c.client_id, clients.c.client_name,
                    func.count(discussions.c.discussion_id).label("discussions"))
             .select_from(clients.outerjoin(discussions, discussions.c.client_id == clients.c.client_id))
             .group_by(clients.c.client_id, clients.c.client_name)
             .order_by(clients.c.client_id))
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(query)]


def count_rows(engine: Optional[Engine] = None) -> Dict[str, int]:
    """Row counts per table (shown in the History tab for verification)."""
    engine = engine or get_engine()
    with engine.connect() as connection:
        return {
            table.name: connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (clients, discussions, discussion_companies)
        }
