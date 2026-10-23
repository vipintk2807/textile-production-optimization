"""Rendering of a stored run (summary, timeline, table). One source: the stored run."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from ..domain.models import OBJECTIVE_LABELS, Objective
from ..domain.timeutil import to_datetime
from ..persistence.repository import StoredRun
from .components import outcome_label, show_badges
from .gantt import build_gantt


def schedule_table(run: StoredRun) -> pd.DataFrame:
    origin = datetime.fromisoformat(run.snapshot.origin_iso)
    om = {o["order_id"]: o for o in (run.metrics or {}).get("orders", [])}
    orders = run.snapshot.order_map()
    rows = []
    for a in sorted(run.assignments, key=lambda x: (x.order_id, x.start, x.operation_id)):
        m = om.get(a.order_id, {})
        tard = m.get("tardiness")
        rows.append(
            {
                "Order ID": a.order_id,
                "Operation ID": a.operation_id,
                "Machine": a.machine_id,
                "Start (min)": a.start,
                "Finish (min)": a.end,
                "Duration (min)": a.duration,
                "Start (calendar)": f"{to_datetime(a.start, origin):%a %d %b %H:%M}",
                "Order due (min)": orders[a.order_id].due_time if a.order_id in orders else None,
                "Order completion (min)": m.get("completion_time"),
                "Tardiness (min)": tard,
                "Status": "unavailable" if tard is None else ("Late" if tard > 0 else "On time"),
            }
        )
    return pd.DataFrame(rows)


def show_run_header(run: StoredRun, stale: bool) -> None:
    label, kind, explanation = outcome_label(run)
    badges = [(f"Solver: {label}", kind)]
    badges.append(
        ("Independent validation: passed", "green")
        if run.accepted
        else ("Independent validation: not accepted", "red")
    )
    badges.append(("Out of date (stale)", "amber") if stale else ("Matches current data", "grey"))
    if run.is_synthetic_data:
        badges.append(("Synthetic data", "grey"))
    show_badges(*badges)
    st.caption(f"Run {run.run_id} | {run.created_at} | {explanation}")
    if stale:
        st.warning(
            "**Schedule out of date.** The planning data or settings changed since this schedule was "
            "generated. Its metrics are historical, not current. Generate a new schedule."
        )


def show_run_details(run: StoredRun) -> None:
    obj_label = OBJECTIVE_LABELS[Objective(run.objective)]
    cols = st.columns(4)
    cols[0].metric("Objective", obj_label.replace("Minimize ", ""))
    cols[1].metric(
        "Objective value (min)", "unavailable" if run.objective_value is None else f"{run.objective_value:g}"
    )
    cols[2].metric("Best bound", "unavailable" if run.best_bound is None else f"{run.best_bound:g}")
    cols[3].metric(
        "Solver runtime (s)", "unavailable" if run.runtime_seconds is None else f"{run.runtime_seconds:.2f}"
    )
    st.caption(
        f"Solver status: {run.solver_status or 'none'} | time limit {run.time_limit:g}s | workers {run.workers} | "
        f"seed {run.random_seed} | OR-Tools {run.solver_version} | model {run.model_version} | "
        f"input fingerprint {run.input_fingerprint[:12]}"
    )
    if run.stopped_at_limit:
        st.info("The search stopped at (or very near) the time limit.")
    if not run.accepted:
        st.error(f"This run was **not accepted** ({run.outcome}). No schedule is shown as valid.")
        if run.detail:
            st.caption(run.detail)
        for issue in run.validation_issues:
            if issue.severity == "error":
                st.markdown(f"- **Validation error:** {issue.message}")
        return
    m = run.metrics or {}
    c = st.columns(5)
    c[0].metric("Scheduled operations", m.get("scheduled_operations"))
    c[1].metric("Late orders", m.get("late_orders"))
    c[2].metric("Total tardiness (min)", m.get("total_tardiness"))
    c[3].metric("Makespan (min)", "unavailable" if m.get("makespan") is None else m["makespan"])
    cm = m.get("changeover_minutes")
    c[4].metric("Changeover time (min)", "not modelled" if cm is None else cm)
    for issue in run.validation_issues:
        if issue.severity == "warning":
            st.caption(f"Note: {issue.message}")


def show_schedule(run: StoredRun) -> None:
    if not run.accepted:
        return
    st.plotly_chart(build_gantt(run), use_container_width=True)
    st.markdown("**Operation schedule**")
    df = schedule_table(run)
    f1, f2, f3 = st.columns(3)
    order = f1.selectbox("Order", ["all", *sorted(df["Order ID"].unique())], key=f"rv_o_{run.run_id}")
    machine = f2.selectbox("Machine", ["all", *sorted(df["Machine"].unique())], key=f"rv_m_{run.run_id}")
    late = f3.selectbox("Status", ["all", "Late", "On time"], key=f"rv_l_{run.run_id}")
    if order != "all":
        df = df[df["Order ID"] == order]
    if machine != "all":
        df = df[df["Machine"] == machine]
    if late != "all":
        df = df[df["Status"] == late]
    st.dataframe(df, use_container_width=True, hide_index=True)
