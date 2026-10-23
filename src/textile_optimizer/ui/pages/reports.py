"""Reports page: order performance, utilization, summary, baseline comparison, history."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...reporting.export import machine_utilization_csv, order_performance_csv, schedule_csv
from ...reporting.metrics import schedule_metrics
from ..components import fmt_time, page_header
from ..context import get_service, show_flash
from ..run_view import show_run_header


def render() -> None:
    page_header(
        "Reports", "Tardiness, completion, utilization and baseline comparison for a validated schedule."
    )
    show_flash()
    svc = get_service()
    run = svc.repo.latest_accepted_run()
    if run is None:
        st.info("No validated schedule exists yet. Generate a schedule on the Schedule page to see reports.")
        _history(svc)
        return
    stale = svc.is_stale(run)
    show_run_header(run, stale)
    metrics = run.metrics
    origin = datetime.fromisoformat(run.snapshot.origin_iso)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["Order performance", "Machine utilization", "Summary", "Baseline comparison", "Run history"]
    )
    with tab1:
        st.caption(
            "Completion = finish of the order's final required operation. Tardiness = max(0, completion - due). Lateness is signed."
        )
        rows = [
            {
                "Order ID": o["order_id"],
                "Due (min)": o["due_time"],
                "Completion (min)": o["completion_time"],
                "Completion (calendar)": fmt_time(o["completion_time"], origin)
                if o["completion_time"] is not None
                else "unavailable",
                "Lateness (min)": o["lateness"],
                "Tardiness (min)": o["tardiness"],
                "Status": "unavailable" if o["is_late"] is None else ("Late" if o["is_late"] else "On time"),
                "Operations": o["operation_count"],
            }
            for o in metrics["orders"]
        ]
        df = pd.DataFrame(rows).sort_values("Tardiness (min)", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download order performance (CSV)",
            order_performance_csv(run),
            file_name=f"orders_run_{run.run_id}.csv",
            mime="text/csv",
        )
    with tab2:
        st.caption(metrics["utilization_definition"])
        mrows = [
            {
                "Machine": m["machine_id"],
                "Processing (min)": m["processing_minutes"],
                "Available (min)": m["available_minutes"],
                "Idle (min)": m["idle_minutes"],
                "Utilization (%)": "unavailable" if m["utilization_pct"] is None else m["utilization_pct"],
            }
            for m in metrics["machines"]
        ]
        st.dataframe(pd.DataFrame(mrows), use_container_width=True, hide_index=True)
        plotted = [m for m in metrics["machines"] if m["utilization_pct"] is not None]
        if plotted:
            fig = go.Figure(
                go.Bar(
                    x=[m["machine_id"] for m in plotted],
                    y=[m["utilization_pct"] for m in plotted],
                    marker_color="#2563EB",
                )
            )
            fig.update_layout(
                title=f"Modelled machine utilization, horizon 0-{run.snapshot.horizon_end} min (run {run.run_id})",
                yaxis_title="Utilization (% of available time)",
                xaxis_title="Machine",
                yaxis={"range": [0, 100]},
                height=360,
                paper_bgcolor="#FFFFFF",
                plot_bgcolor="#FFFFFF",
            )
            st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "This is a model-derived measure, not equipment effectiveness. Machines with no available time show 'unavailable'."
        )
        st.download_button(
            "Download utilization (CSV)",
            machine_utilization_csv(run),
            file_name=f"utilization_run_{run.run_id}.csv",
            mime="text/csv",
        )
    with tab3:
        cols = st.columns(4)
        cols[0].metric("Total tardiness (min)", metrics["total_tardiness"])
        cols[1].metric("Late orders", metrics["late_orders"])
        cols[2].metric("Makespan (min)", metrics["makespan"])
        wt = metrics["weighted_tardiness"]
        cols[3].metric("Weighted tardiness", "unavailable (no weights)" if wt is None else wt)
        st.metric("Total scheduled processing (min)", metrics["total_processing_minutes"])
        cm = metrics["changeover_minutes"]
        st.write(
            "Changeover time: "
            + ("not modelled in this run" if cm is None else f"{cm} min between consecutive operations")
        )
        st.caption(
            f"Optimized objective: {run.objective}. Objective values for different objectives measure different criteria and must not be compared as better/worse."
        )
        st.download_button(
            "Download schedule (CSV)",
            schedule_csv(run, stale),
            file_name=f"schedule_run_{run.run_id}.csv",
            mime="text/csv",
        )
    with tab4:
        _baseline(svc, run)
    with tab5:
        _history(svc)


def _baseline(svc, run) -> None:
    base = svc.baseline_for(run)
    st.markdown(f"**Baseline method:** {base.method}")
    st.caption(
        f"Input: the run's own snapshot (fingerprint {run.input_fingerprint[:12]}). Objective optimized by the solver: {run.objective}."
    )
    if base.candidate is None or not base.valid:
        st.warning(base.message)
        return
    bm = schedule_metrics(run.snapshot, base.candidate.assignments)
    om = run.metrics
    rows = []
    for label, key in [
        ("Total tardiness (min)", "total_tardiness"),
        ("Late orders", "late_orders"),
        ("Makespan (min)", "makespan"),
        ("Scheduled processing (min)", "total_processing_minutes"),
        ("Changeover time (min)", "changeover_minutes"),
    ]:
        fmt = lambda v: "not modelled" if v is None else v  # noqa: E731
        rows.append({"Metric": label, "Baseline": fmt(bm[key]), "Optimized run": fmt(om[key])})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "Both schedules passed independent validation on identical data. Results are computed now from these inputs; "
        "the optimizer only minimizes its selected objective, so other metrics may be worse. "
        "Synthetic/demo data does not indicate real-factory improvement."
    )


def _history(svc) -> None:
    runs = svc.repo.list_runs()
    if not runs:
        return
    rows = [
        {
            "Run": r.run_id,
            "Created": r.created_at,
            "Outcome": r.outcome,
            "Solver status": r.solver_status or "-",
            "Objective": r.objective,
            "Objective value": r.objective_value,
            "Time limit (s)": r.time_limit,
            "Runtime (s)": None if r.runtime_seconds is None else round(r.runtime_seconds, 2),
            "Fingerprint": r.input_fingerprint[:12],
            "Current inputs": "yes" if not svc.is_stale(r) else "no (stale)",
        }
        for r in runs
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Compare runs only when they share the same objective and input fingerprint.")
