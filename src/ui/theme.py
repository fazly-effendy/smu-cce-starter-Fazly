"""Nimbus design system: one palette, one type scale, shared HTML helpers.

Rules
-----
- One accent colour (blue) for interactive elements, tickers and the first chart line.
- Green and red only for up/down (returns, beat/miss, buy/sell); grey for neutral.
- Type scale: page title > section title > card title > body > caption.

Streamlit options are used wherever they exist; the CSS below only covers what
they cannot (content width, chips, table alignment and the type scale).
"""

from __future__ import annotations

import html
from typing import Optional

import streamlit as st

ACCENT = "#2563EB"
UP = "#16A34A"
DOWN = "#DC2626"
NEUTRAL = "#94A3B8"
# Company series colours: accent first, then distinct colour-blind-friendly hues
# (no pure green or red, which are reserved for up/down).
SERIES = [ACCENT, "#F59E0B", "#0891B2", "#DB2777", "#7C3AED", "#65A30D"]
# Analyst recommendation scale, diverging green -> grey -> red.
RATING_COLOURS = ["#15803D", "#4ADE80", "#94A3B8", "#F87171", "#B91C1C"]

CONTENT_MAX_WIDTH = 1300

CSS = f"""
<style>
/* Wide content area, capped so it does not over-stretch on large monitors.
   Applies whatever the browser's own "Wide mode" setting is. */
[data-testid="stMainBlockContainer"], .block-container {{
  max-width: {CONTENT_MAX_WIDTH}px !important;
  width: 100%;
  padding: 1.5rem 2rem 3rem 2rem;
}}

/* Header */
.nb-header {{display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap; margin: 0 0 .6rem 0;}}
.nb-header .nb-logo {{font-size: 1.5rem; line-height: 1;}}
.nb-header .nb-title {{font-size: 1.6rem; font-weight: 700; letter-spacing: -.01em;}}
.nb-header .nb-tagline {{font-size: .9rem; opacity: .65;}}

/* Type scale */
.nb-section {{font-size: 1.05rem; font-weight: 600; margin: 1.4rem 0 .5rem 0;}}
.nb-card-title {{font-size: .98rem; font-weight: 600; margin-bottom: .15rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}}
.nb-muted {{font-size: .82rem; opacity: .65;}}
[data-testid="stCaptionContainer"] {{font-size: .8rem;}}

/* Chips: ticker, status and result pills share one shape */
.nb-chip {{display: inline-block; padding: .05rem .5rem; border-radius: 999px; font-size: .78rem;
  font-weight: 600; line-height: 1.5; white-space: nowrap; font-variant-numeric: tabular-nums;
  vertical-align: middle;}}
.nb-chip.accent {{background: rgba(37,99,235,.16); color: #60A5FA;}}
.nb-chip.up {{background: rgba(22,163,74,.16); color: #4ADE80;}}
.nb-chip.down {{background: rgba(220,38,38,.16); color: #F87171;}}
.nb-chip.neutral {{background: rgba(148,163,184,.16); color: #CBD5E1;}}

/* Small label/value pairs inside company cards */
.nb-stats {{display: grid; grid-template-columns: 1fr 1fr; gap: .25rem 1rem; margin-top: .35rem;}}
.nb-stat .nb-label {{display: block; font-size: .75rem; opacity: .65;}}
.nb-stat .nb-value {{display: block; font-size: 1.05rem; font-weight: 600; white-space: nowrap;
  font-variant-numeric: tabular-nums;}}
.nb-flag {{cursor: help; color: #FBBF24; font-size: .8rem; margin-left: .25rem;}}

/* Static tables: numbers right-aligned in tabular figures, zebra rows, labels on one line */
[data-testid="stTable"] table {{font-variant-numeric: tabular-nums; width: 100%;}}
[data-testid="stTable"] td {{text-align: right; white-space: nowrap;}}
[data-testid="stTable"] th {{white-space: nowrap;}}
[data-testid="stTable"] tbody th {{text-align: left; font-weight: 500;}}
[data-testid="stTable"] tbody tr:nth-child(even) {{background: rgba(148,163,184,.06);}}

/* News meta line */
.nb-meta {{font-size: .82rem; opacity: .85; margin: .1rem 0 .3rem 0;}}

/* Sidebar rhythm */
section[data-testid="stSidebar"] .nb-side-title {{font-size: .8rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; opacity: .7; margin: 1.1rem 0 .4rem 0;}}
section[data-testid="stSidebar"] button p {{font-size: .82rem; white-space: nowrap;}}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text: Optional[str]) -> str:
    return html.escape(text or "")


def chip(text: str, tone: str = "accent", tooltip: Optional[str] = None) -> str:
    """HTML pill. tone: accent | up | down | neutral."""
    title = f' title="{esc(tooltip)}"' if tooltip else ""
    return f'<span class="nb-chip {tone}"{title}>{esc(text)}</span>'


def flag(tooltip: str) -> str:
    """Subtle warning marker with an explanation on hover."""
    return f'<span class="nb-flag" title="{esc(tooltip)}">⚠ unusual</span>'


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def section(title: str) -> None:
    html_block(f'<div class="nb-section">{esc(title)}</div>')


def header(tagline: str) -> None:
    html_block(
        '<div class="nb-header"><span class="nb-logo">☁️</span><span class="nb-title">Nimbus</span>'
        f'<span class="nb-tagline">{esc(tagline)}</span></div>'
    )


def side_title(title: str) -> None:
    html_block(f'<div class="nb-side-title">{esc(title)}</div>')


def tone_for(value: Optional[float]) -> str:
    if value is None or value == 0:
        return "neutral"
    return "up" if value > 0 else "down"
