"""Plotly Gantt-style timeline built from the stored, validated run only."""

from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go

from ..domain.timeutil import to_datetime
from ..persistence.repository import StoredRun

_PALETTE = ["#2563EB", "#0F766E", "#B45309", "#7C3AED", "#BE185D", "#4D7C0F", "#0369A1", "#9A3412"]


def unavailable_bands(windows, horizon: int) -> list[tuple[int, int]]:
    bands, cursor = [], 0
    for start, end in sorted(windows):
        if start > cursor:
            bands.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < horizon:
        bands.append((cursor, horizon))
    return bands


def build_gantt(run: StoredRun) -> go.Figure:
    snap = run.snapshot
    origin = datetime.fromisoformat(snap.origin_iso)
    machines = sorted(m.machine_id for m in snap.machines)
    order_ids = sorted(o.order_id for o in snap.orders)
    colour = {o: _PALETTE[i % len(_PALETTE)] for i, o in enumerate(order_ids)}
    fig = go.Figure()
    gray_y, gray_base, gray_len = [], [], []
    for m in snap.machines:
        for a, b in unavailable_bands(m.windows, snap.horizon_end):
            gray_y.append(m.machine_id)
            gray_base.append(a)
            gray_len.append(b - a)
    if gray_y:
        fig.add_bar(
            y=gray_y,
            x=gray_len,
            base=gray_base,
            orientation="h",
            name="Unavailable",
            marker_color="#E2E8F0",
            hovertemplate="Unavailable [%{base}, %{x}+%{base})<extra></extra>",
            showlegend=True,
        )
    for oid in order_ids:
        items = [a for a in run.assignments if a.order_id == oid]
        if not items:
            continue
        fig.add_bar(
            y=[a.machine_id for a in items],
            x=[a.end - a.start for a in items],
            base=[a.start for a in items],
            orientation="h",
            name=oid,
            marker_color=colour[oid],
            text=[a.operation_id for a in items],
            textposition="inside",
            insidetextanchor="middle",
            customdata=[
                [
                    a.operation_id,
                    a.start,
                    a.end,
                    f"{to_datetime(a.start, origin):%a %d %b %H:%M}",
                    f"{to_datetime(a.end, origin):%a %d %b %H:%M}",
                ]
                for a in items
            ],
            hovertemplate=(
                "<b>%{customdata[0]}</b> (order " + oid + ")<br>Machine: %{y}<br>"
                "Start: %{customdata[1]} min (%{customdata[3]})<br>"
                "End: %{customdata[2]} min (%{customdata[4]})<extra></extra>"
            ),
        )
    fig.update_layout(
        barmode="overlay",
        title=f"Schedule timeline - run {run.run_id} (validated)",
        xaxis_title=f"Minutes from planning origin ({origin:%Y-%m-%d %H:%M}); horizon 0-{snap.horizon_end}",
        yaxis_title="Machine",
        yaxis={"categoryorder": "array", "categoryarray": machines[::-1]},
        xaxis={"range": [0, snap.horizon_end]},
        height=max(320, 90 * len(machines) + 140),
        legend_title="Order",
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font={"color": "#0F172A"},
    )
    return fig
