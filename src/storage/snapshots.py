"""Briefing snapshot files (Features 3 and 4: storage).

Follows the Lesson 7 design: each saved briefing becomes a Markdown file in
analyses-data/ (the local disk in Codespaces, the EBS root volume on EC2).
A JSON file with the same name is written next to it so the briefing can be
reopened in the app exactly as saved, including the price chart.

Reused from the earlier src/analysis_storage.py: safe filename segments,
exclusive file creation (never overwrite), and the path check on reading.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Tuple

from analytics.formatting import (
    NOT_AVAILABLE,
    format_date,
    format_money,
    format_multiple,
    format_percent,
    format_price,
    format_timestamp,
)
from analytics.ratios import RATIO_LABELS
from config import data_dir
from models.briefing import Briefing


def _filename_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-")
    if not segment:
        raise ValueError("Filename segment must contain letters or numbers.")
    return segment


def snapshot_stem(briefing: Briefing) -> str:
    """e.g. AAPL-MSFT__company-briefing__20261024T130501Z__1a2b3c4d"""
    tickers = _filename_segment("-".join(briefing.successful_tickers or briefing.tickers))[:60]
    created = datetime.fromisoformat(briefing.created_at.replace("Z", "+00:00"))
    timestamp = created.strftime("%Y%m%dT%H%M%SZ")
    return f"{tickers}__{_filename_segment(briefing.analysis_type)}__{timestamp}__{briefing.briefing_id[:8]}"


def _write_new(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:  # "x" fails rather than overwrite
        handle.write(content)


def write_snapshot(briefing: Briefing) -> Tuple[str, str]:
    """Write the Markdown and JSON files. Returns (markdown filename, json filename)."""
    folder = data_dir()
    stem = snapshot_stem(briefing)
    markdown_path = folder / f"{stem}.md"
    json_path = folder / f"{stem}.json"
    _write_new(json_path, json.dumps(briefing.to_dict(), indent=2, ensure_ascii=False))
    try:
        _write_new(markdown_path, briefing_markdown(briefing))
    except Exception:
        json_path.unlink(missing_ok=True)
        raise
    return markdown_path.name, json_path.name


def delete_snapshot(*filenames: str) -> None:
    """Remove snapshot files (used to roll back when the database save fails)."""
    for filename in filenames:
        try:
            _resolve(filename).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def _resolve(filename: str) -> Path:
    """Only allow plain filenames inside the data folder."""
    folder = data_dir().resolve()
    path = (folder / filename).resolve()
    if path.parent != folder or path.suffix.lower() not in {".md", ".json"}:
        raise ValueError("The requested file is not a saved briefing.")
    return path


def read_snapshot(json_filename: str) -> Briefing:
    """Load a saved briefing from its JSON file. Never calls Yahoo."""
    path = _resolve(json_filename)
    if not path.exists():
        raise FileNotFoundError(
            f"The saved file {json_filename} was not found in {path.parent}. "
            "It may have been created on a different machine or deleted."
        )
    return Briefing.from_dict(json.loads(path.read_text(encoding="utf-8")))


def read_markdown(markdown_filename: str) -> str:
    return _resolve(markdown_filename).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Markdown export
# --------------------------------------------------------------------------

def _cell(text: str) -> str:
    return str(text).replace("|", r"\|").replace("\n", " ")


def _table(headers, rows) -> str:
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def briefing_markdown(briefing: Briefing) -> str:
    companies = briefing.companies
    tickers = [c.ticker for c in companies]
    out = [
        f"# Nimbus company briefing: {', '.join(tickers) or 'no companies'}",
        "",
        "## Briefing details",
        f"- **Briefing ID:** {briefing.briefing_id}",
        f"- **Analysis type:** {briefing.analysis_type}",
        f"- **Generated:** {format_timestamp(briefing.created_at)}",
        f"- **Saved:** {format_timestamp(briefing.saved_at)}",
        f"- **Analysis period (share prices):** {briefing.analysis_period}"
        + (f" ({briefing.price_window[0]} to {briefing.price_window[1]})" if briefing.price_window else ""),
        f"- **Tickers requested:** {', '.join(briefing.tickers)}",
        f"- **App version:** {briefing.app_version} (schema {briefing.schema_version})",
    ]
    if briefing.failed_tickers:
        out.append("- **Not retrieved:** " + "; ".join(f"{t}: {r}" for t, r in briefing.failed_tickers.items()))

    out += ["", "## Company comparison", ""]
    rows = [
        ["Last close"] + [f"{format_price(c.last_close, c.currency)} ({c.last_close_date})" for c in companies],
        ["Holding-period return"] + [format_percent(briefing.holding_period_returns.get(c.ticker)) for c in companies],
        ["Market capitalisation"] + [format_money(c.market_cap, c.currency) for c in companies],
        ["P/E ratio (trailing)"] + [format_multiple(c.pe_ratio) for c in companies],
    ]
    rows += [[label] + [format_percent(c.ratios.get(key)) for c in companies] for key, label in RATIO_LABELS.items()]
    rows.append(["Fiscal year used"] + [c.fiscal_year_end or NOT_AVAILABLE for c in companies])
    out.append(_table(["Measure"] + tickers, rows))

    for company in companies:
        out += ["", f"## {company.name} ({company.ticker})", ""]
        out.append(
            f"Source: [{company.source_name}]({company.source_url}), retrieved {format_timestamp(company.retrieved_at)}. "
            f"Statement figures in {company.financial_currency or 'reporting currency'}."
        )
        if company.financials:
            years = sorted({y for values in company.financials.values() for y in values}, reverse=True)
            out += ["", "### Financial statements (annual)", ""]
            out.append(_table(
                ["Line item"] + [f"FY {y}" for y in years],
                [[item] + [format_money(values.get(y), company.financial_currency) for y in years]
                 for item, values in company.financials.items()],
            ))
        out += ["", "### Analyst ratings", ""]
        if company.ratings:
            keys = ["strongBuy", "buy", "hold", "sell", "strongSell"]
            out.append(_table(
                ["Strong buy", "Buy", "Hold", "Sell", "Strong sell"],
                [[company.ratings.get(k) if company.ratings.get(k) is not None else NOT_AVAILABLE for k in keys]],
            ))
        else:
            out.append("No analyst ratings available.")
        out += ["", "### News", ""]
        if company.news:
            for item in company.news:
                title = f"[{item.headline}]({item.source_url})" if item.source_url else item.headline
                meta = " · ".join(x for x in [item.publisher, format_date(item.published_at) if item.published_at else None] if x)
                out.append(f"- **{title}**" + (f" ({meta})" if meta else ""))
                out.append(f"  {item.summary or 'No summary provided by the source.'}")
        else:
            out.append("No recent news available.")
        for warning in company.warnings:
            out.append(f"\n> Note: {warning}")

    out += ["", "## RM notes", ""]
    note = briefing.note
    if note:
        out += [
            f"- **Client / briefing reference:** {note.client_reference}",
            f"- **Meeting date:** {format_date(note.meeting_date)}",
            f"- **Next review date:** {format_date(note.next_review_date)}",
            f"- **Note recorded:** {format_timestamp(note.created_at)}",
            "",
            "**Discussion summary**", "", note.discussion_summary or NOT_AVAILABLE, "",
            "**Client priorities or concerns**", "", note.client_priorities or NOT_AVAILABLE, "",
            "**Follow-up actions**", "", note.follow_up_actions or NOT_AVAILABLE, "",
            "**Other notes**", "", note.free_text or NOT_AVAILABLE,
        ]
    else:
        out.append("No RM note recorded.")
    return "\n".join(out).rstrip() + "\n"
