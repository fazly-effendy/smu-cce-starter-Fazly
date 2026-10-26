"""Save and reopen client discussions: database records + a Markdown file together."""

from __future__ import annotations

from dataclasses import replace
from typing import Tuple

from models.briefing import Briefing, RmNote
from services.briefing_builder import utc_now_iso
from storage import database, snapshots


class SaveResult:
    def __init__(self, briefing: Briefing, filename: str, created: bool):
        self.briefing = briefing
        self.filename = filename
        self.created = created  # False when this discussion had already been saved


def save_discussion(briefing: Briefing, note: RmNote) -> SaveResult:
    """Save the discussion (companies + note) exactly once.

    Order: check the note, write the Markdown file, then insert the database rows
    (client, discussion with its JSON snapshot, one row per company) in one
    transaction. If the database insert fails, the file is deleted again, so the
    two stores never disagree.
    """
    existing = database.get_discussion(briefing.briefing_id)
    if existing:
        return SaveResult(briefing, existing["filename"], created=False)

    note = replace(note, client_id=database.normalise_client_id(note.client_id))
    if not (note.client_interests or "").strip():
        raise ValueError("Notes about the client's interests are required.")
    to_save = replace(briefing, note=note, saved_at=utc_now_iso())
    markdown_name = snapshots.write_markdown(to_save)
    try:
        created = database.insert_discussion(to_save, markdown_name)
    except Exception:
        snapshots.delete_snapshot(markdown_name)
        raise
    if not created:  # saved concurrently by another click: keep the first copy only
        snapshots.delete_snapshot(markdown_name)
        row = database.get_discussion(briefing.briefing_id)
        return SaveResult(to_save, row["filename"] if row else markdown_name, created=False)
    return SaveResult(to_save, markdown_name, created=True)


def open_discussion(discussion_id: str) -> Tuple[Briefing, dict]:
    """Load a saved discussion from the database. Never retrieves fresh data.

    Returns (the snapshot as saved, the database row). Works on any app server,
    because the snapshot is stored in the database, not only on one server's disk.
    """
    row = database.get_discussion(discussion_id)
    if row is None:
        raise LookupError(f"No saved discussion with ID {discussion_id}.")
    briefing = snapshots.briefing_from_json(row["snapshot_json"])
    if briefing.briefing_id != discussion_id:
        raise ValueError("The stored snapshot does not match the database record.")
    return briefing, row
