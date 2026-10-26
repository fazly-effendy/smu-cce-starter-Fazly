"""Altair charts for the Compare tab (rendered with st.altair_chart)."""

from __future__ import annotations

from typing import Optional

import altair as alt
import pandas as pd

from analytics.formatting import NOT_AVAILABLE, format_price
from models.briefing import Briefing
from ui.theme import NEUTRAL, RATING_COLOURS, SERIES

RATING_BUCKETS = [("strongBuy", "Strong buy"), ("buy", "Buy"), ("hold", "Hold"), ("sell", "Sell"),
                  ("strongSell", "Strong sell")]
BAR_ROW_PX = 30  # height per company in the analyst chart
MIN_LABEL_SHARE = 0.08  # only print a % inside segments at least this wide


def price_chart(briefing: Briefing) -> Optional[alt.LayerChart]:
    """Rebased share prices (start = 100) with a dashed 100 line, labelled series and hover tooltips.

    Points are sorted by date and missing values dropped, so each line is drawn
    continuously across the dates every company traded.
    """
    currencies = {c.ticker: c.currency for c in briefing.companies}
    rows = []
    for ticker, series in briefing.price_index.items():
        prices = briefing.price_history.get(ticker, {})
        for day, rebased in series.items():
            if rebased is None:
                continue
            rows.append({
                "Date": day,
                "Company": ticker,
                "Rebased": float(rebased),
                "Close": format_price(prices.get(day), currencies.get(ticker)) if prices.get(day) else NOT_AVAILABLE,
            })
    if not rows:
        return None
    data = pd.DataFrame(rows)
    data["Date"] = pd.to_datetime(data["Date"])
    data = data.dropna(subset=["Rebased"]).sort_values(["Company", "Date"])
    tickers = list(briefing.price_index)
    colours = SERIES[:len(tickers)]

    low = min(data["Rebased"].min(), 100.0)
    high = max(data["Rebased"].max(), 100.0)
    pad = max((high - low) * 0.08, 2.0)

    base = alt.Chart(data).encode(
        x=alt.X("Date:T", title=None, scale=alt.Scale(nice=False), axis=alt.Axis(format="%b %Y", tickCount=6)),
        y=alt.Y("Rebased:Q", title="Rebased (start = 100)",
                scale=alt.Scale(domain=[low - pad, high + pad], zero=False, nice=False)),
        color=alt.Color("Company:N", scale=alt.Scale(domain=tickers, range=colours),
                        legend=alt.Legend(orient="top", title=None)),
    )
    hover = alt.selection_point(fields=["Date"], nearest=True, on="mouseover", empty=False, clear="mouseout")
    lines = base.mark_line(strokeWidth=2.2, interpolate="linear").encode(order=alt.Order("Date:T"))
    points = base.mark_circle(size=60).encode(
        opacity=alt.condition(hover, alt.value(1.0), alt.value(0.0)),
        tooltip=[
            alt.Tooltip("Date:T", format="%-d %b %Y"),
            alt.Tooltip("Company:N"),
            alt.Tooltip("Rebased:Q", format=".1f", title="Rebased"),
            alt.Tooltip("Close:N", title="Adjusted close"),
        ],
    ).add_params(hover)
    last = data.sort_values("Date").groupby("Company", as_index=False).tail(1)
    end_labels = alt.Chart(last).mark_text(align="left", dx=6, fontSize=11, fontWeight="bold").encode(
        x="Date:T", y="Rebased:Q", text="Company:N",
        color=alt.Color("Company:N", scale=alt.Scale(domain=tickers, range=colours), legend=None),
    )
    cursor = alt.Chart(data).mark_rule(color=NEUTRAL, strokeWidth=1).encode(x="Date:T").transform_filter(hover)
    baseline = alt.Chart(pd.DataFrame({"Rebased": [100.0]})).mark_rule(
        strokeDash=[6, 4], color=NEUTRAL, strokeWidth=1.2
    ).encode(y="Rebased:Q")
    return (
        alt.layer(baseline, lines, cursor, points, end_labels)
        .properties(height=360, width="container", padding={"left": 5, "right": 55, "top": 5, "bottom": 5})
    )


def ratings_chart(briefing: Briefing) -> Optional[alt.LayerChart]:
    """Share of analysts per recommendation: one 30px bar per company, % printed inside wide segments."""
    rows = []
    for company in briefing.companies:
        counts = [(label, (company.ratings or {}).get(key) or 0) for key, label in RATING_BUCKETS]
        total = sum(count for _, count in counts)
        if not total:
            continue
        start = 0.0
        for order, (label, count) in enumerate(counts):
            share = count / total
            rows.append({"Company": company.ticker, "Rating": label, "Analysts": count, "Share": share,
                         "Start": start, "End": start + share, "Mid": start + share / 2, "Order": order,
                         "Label": f"{share:.0%}" if share >= MIN_LABEL_SHARE else ""})
            start += share
    if not rows:
        return None
    data = pd.DataFrame(rows)
    data = data[data["Analysts"] > 0]
    tickers = list(dict.fromkeys(data["Company"]))
    labels = [label for _, label in RATING_BUCKETS]

    y = alt.Y("Company:N", title=None, sort=tickers, scale=alt.Scale(paddingInner=0.3),
              axis=alt.Axis(labelFontSize=12, labelFontWeight="bold", ticks=False, domain=False, labelPadding=8))
    bars = alt.Chart(data).mark_bar(cornerRadius=2).encode(
        y=y,
        x=alt.X("Start:Q", title="Share of analysts (current month)", scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%", tickCount=5, grid=False)),
        x2="End:Q",
        color=alt.Color("Rating:N", scale=alt.Scale(domain=labels, range=RATING_COLOURS),
                        legend=alt.Legend(orient="top", title=None, direction="horizontal")),
        tooltip=[alt.Tooltip("Company:N"), alt.Tooltip("Rating:N"), alt.Tooltip("Analysts:Q"),
                 alt.Tooltip("Share:Q", format=".0%")],
    )
    text = alt.Chart(data).mark_text(fontSize=11, fontWeight="bold", color="#0B1220").encode(
        y=y, x="Mid:Q", text="Label:N",
    )
    return alt.layer(bars, text).properties(height=alt.Step(BAR_ROW_PX), width="container")
