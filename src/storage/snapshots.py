"""Client-discussion files (Features 3 and 4: storage).

Follows the Lesson 7 design: each saved discussion becomes a readable Markdown
file in analyses-data/ (the local disk in Codespaces, the EBS root volume on
EC2). The complete snapshot used to reopen it in the app is stored as JSON in
the database (see storage/database.py), so any app server can reopen it.

Reused from the earlier src/analysis_storage.py: safe filename segments,
exclusive file creation (never overwrite), and the path check on reading.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from analytics.formatting import (
    NOT_AVAILABLE,
    format_date,
    format_eps,
    format_money,
    format_multiple,
    format_percent,
    format_price,
    format_timestamp,
)
from analytics.ratios import RATIO_LABELS, format_ratio
from config import data_dir
from models.briefing import Briefing
from services.yahoo import STATEMENT_ITEMS


def _filename_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-")
    if not segment:
        raise ValueError("Filename segment must contain letters or numbers.")
    return segment


def snapshot_stem(briefing: Briefing) -> str:
    """e.g. C-1001__AAPL-MSFT__20261027T130501Z__1a2b3c4d (client, companies, saved time, ID)."""
    tickers = _filename_segment("-".join(briefing.successful_tickers or briefing.tickers))[:60]
    client = _filename_segment(briefing.note.client_id)[:32] if briefing.note and briefing.note.client_id else "no-client"
    created = datetime.fromisoformat((briefing.saved_at or briefing.created_at).replace("Z", "+00:00"))
    timestamp = created.strftime("%Y%m%dT%H%M%SZ")
    return f"{client}__{tickers}__{timestamp}__{briefing.briefing_id[:8]}"


def _write_new(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:  # "x" fails rather than overwrite
        handle.write(content)


def write_markdown(briefing: Briefing) -> str:
    """Write the discussion's Markdown file (never overwrites). Returns its filename."""
    path = data_dir() / f"{snapshot_stem(briefing)}.md"
    _write_new(path, briefing_markdown(briefing))
    return path.name


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


def briefing_from_json(text: str) -> Briefing:
    """Rebuild a saved discussion from its JSON snapshot (as stored in the database)."""
    return Briefing.from_dict(json.loads(text))


def read_markdown(markdown_filename: str) -> str:
    return _resolve(markdown_filename).read_text(encoding="utf-8")


def markdown_for(briefing: Briefing, markdown_filename: str) -> str:
    """The saved Markdown file if this server has it, otherwise the same content rebuilt from
    the snapshot (e.g. when the discussion was saved through another app server)."""
    try:
        return read_markdown(markdown_filename)
    except (OSError, ValueError):
        return briefing_markdown(briefing)


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
    note = briefing.note
    out = [
        f"# Nimbus client discussion: {note.client_id if note else 'no client'} · {', '.join(tickers) or 'no companies'}",
        "",
        "## Discussion",
        f"- **Client ID:** {note.client_id if note else NOT_AVAILABLE}"
        + (f" ({note.client_name})" if note and note.client_name else ""),
        f"- **Discussion date:** {format_date(note.discussion_date) if note else NOT_AVAILABLE}",
        f"- **Companies:** {', '.join(tickers) or NOT_AVAILABLE}",
        "",
        "**Client's interests**",
        "",
        (note.client_interests if note and note.client_interests else NOT_AVAILABLE),
        "",
        "## Snapshot details",
        f"- **Discussion ID:** {briefing.briefing_id}",
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
        ["Stock price at discussion (close)"] + [f"{format_price(c.last_close, c.currency)} ({c.last_close_date})" for c in companies],
        ["Holding-period return"] + [format_percent(briefing.holding_period_returns.get(c.ticker)) for c in companies],
        ["Market capitalisation"] + [format_money(c.market_cap, c.currency) for c in companies],
        ["P/E ratio (trailing)"] + [format_multiple(c.pe_ratio) for c in companies],
    ]
    rows += [[label] + [format_ratio(key, c.ratios.get(key)) for c in companies] for key, label in RATIO_LABELS.items()]
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
                [[item] + [format_money(company.financials.get(item, {}).get(y), company.financial_currency)
                           for y in years]
                 for item in dict.fromkeys([*STATEMENT_ITEMS, *company.financials])],
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
        view = company.analyst or {}
        if view:
            out.append("")
            out.append(
                f"Consensus: {(view.get('recommendation') or NOT_AVAILABLE).title()} "
                f"({view.get('analysts') or NOT_AVAILABLE} analysts); mean price target "
                f"{format_price(view.get('target_mean'), company.currency)}, upside {format_percent(view.get('upside'))} "
                f"(range {format_price(view.get('target_low'), company.currency)} to "
                f"{format_price(view.get('target_high'), company.currency)})."
            )
        earnings = company.earnings or {}
        out += ["", "### Earnings", ""]
        if earnings:
            out.append(f"- Next earnings: {format_date(earnings.get('next_date'))}, EPS estimate "
                       f"{format_eps(earnings.get('next_eps_estimate'))}")
            out.append(f"- Last reported: {format_date(earnings.get('last_date'))}, EPS "
                       f"{format_eps(earnings.get('last_eps_actual'))} vs estimate "
                       f"{format_eps(earnings.get('last_eps_estimate'))}"
                       + (f" ({earnings['last_result']}, surprise {format_percent(earnings.get('last_surprise'))})"
                          if earnings.get("last_result") else ""))
        else:
            out.append("No earnings data available.")
        out += ["", "### News", ""]
        if company.news:
            for item in company.news:
                title = f"[{item.headline}]({item.source_url})" if item.source_url else item.headline
                source = item.publisher or (f"via {item.via} (publisher not listed)" if item.via else None)
                meta = " · ".join(x for x in [source, format_date(item.published_at) if item.published_at else None] if x)
                out.append(f"- **{title}**" + (f" ({meta})" if meta else ""))
                summary = item.summary or "No summary provided by the source."
                if item.summary and item.summary_source:
                    summary += f" (summary via {item.summary_source})"
                out.append(f"  {summary}")
        else:
            out.append("No recent news available.")
        for warning in company.warnings:
            out.append(f"\n> Note: {warning}")

    out += ["", "## Discussion notes", ""]
    if note:
        out += [
            f"- **Next review date:** {format_date(note.next_review_date)}",
            f"- **Note recorded:** {format_timestamp(note.created_at)}",
            "",
            "**Discussion summary**", "", note.notes or NOT_AVAILABLE, "",
            "**Follow-up actions**", "", note.follow_up_actions or NOT_AVAILABLE, "",
            "**Other notes**", "", note.free_text or NOT_AVAILABLE,
        ]
        if note.saved_articles:
            out += ["", "**Saved articles**", ""]
            for article in note.saved_articles:
                headline = article.get("headline") or "Untitled"
                title = f"[{headline}]({article['source_url']})" if article.get("source_url") else headline
                meta = " · ".join(x for x in [article.get("ticker"), article.get("publisher"),
                                               format_date(article.get("published_at")) if article.get("published_at") else None] if x)
                out.append(f"- {title}" + (f" ({meta})" if meta else ""))
    else:
        out.append("No discussion note recorded.")
    return "\n".join(out).rstrip() + "\n"
