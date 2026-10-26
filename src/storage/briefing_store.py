"""Save and reopen complete briefings: snapshot files + database metadata together."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional, Tuple

from sqlalchemy import select

from models.briefing import Briefing, RmNote
from services.briefing_builder import utc_now_iso
from storage import database, snapshots


class SaveResult:
    def __init__(self, briefing: Briefing, filename: str, created: bool):
        self.briefing = briefing
        self.filename = filename
        self.created = created  # False when this briefing had already been saved


def save_briefing(briefing: Briefing, note: Optional[RmNote]) -> SaveResult:
    """Save the briefing and RM note exactly once.

    Order: write the snapshot files, then insert the database rows in one
    transaction. If the database insert fails, the files are deleted again,
    so the two stores never disagree.
    """
    existing = find_row(briefing.briefing_id)
    if existing:
        return SaveResult(briefing, existing["filename"], created=False)

    to_save = replace(briefing, note=note, saved_at=utc_now_iso())
    markdown_name, json_name = snapshots.write_snapshot(to_save)
    try:
        created = database.insert_briefing(to_save, markdown_name, json_name)
    except Exception:
        snapshots.delete_snapshot(markdown_name, json_name)
        raise
    if not created:  # saved concurrently by another click: keep the first copy only
        snapshots.delete_snapshot(markdown_name, json_name)
        row = find_row(briefing.briefing_id)
        return SaveResult(to_save, row["filename"] if row else markdown_name, created=False)
    return SaveResult(to_save, markdown_name, created=True)


def find_row(briefing_id: str) -> Optional[dict]:
    engine = database.get_engine()
    with engine.connect() as connection:
        row = connection.execute(
            select(database.briefings).where(database.briefings.c.briefing_id == briefing_id)
        ).first()
    return dict(row._mapping) if row else None


def open_briefing(briefing_id: str) -> Tuple[Briefing, dict]:
    """Load a saved briefing from its snapshot file. Never retrieves fresh data."""
    row = find_row(briefing_id)
    if row is None:
        raise LookupError(f"No saved briefing with ID {briefing_id}.")
    briefing = snapshots.read_snapshot(row["json_filename"])
    if briefing.briefing_id != briefing_id:
        raise ValueError("The snapshot file does not match the database record.")
    return briefing, row
