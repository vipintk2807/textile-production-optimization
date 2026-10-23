"""Schedule page: settings, input validation, explicit Generate Schedule, results."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from ... import config
from ...domain.models import OBJECTIVE_LABELS, ChangeoverRule, Objective, PlanningSettings
from ...errors import RunInProgressError, TextileOptimizerError
from ...reporting.export import schedule_csv
from ...services.planning_service import build_record
from ..components import page_header, show_issues
from ..context import flash, get_service, show_flash
from ..run_view import show_run_details, show_run_header, show_schedule


def _settings_form(svc, settings: PlanningSettings) -> None:
    with st.expander("Scheduling settings", expanded=False), st.form("settings_form"):
        a, b = st.columns(2)
        origin_date = a.date_input("Planning origin date (minute 0)", value=settings.origin.date())
        origin_time = b.time_input("Planning origin time", value=settings.origin.time())
        c, d, e = st.columns(3)
        horizon = c.number_input(
            "Horizon end (min from origin)",
            min_value=1,
            value=settings.horizon_end,
            step=60,
            help="Operations may finish exactly at this minute but not later.",
        )
        objectives = list(Objective)
        objective = d.selectbox(
            "Optimization objective",
            objectives,
            index=objectives.index(settings.objective),
            format_func=lambda o: OBJECTIVE_LABELS[o],
        )
        limit = e.number_input(
            "Solver time limit (s)",
            min_value=config.MIN_TIME_LIMIT_SECONDS,
            max_value=config.MAX_TIME_LIMIT_SECONDS,
            value=settings.time_limit_seconds,
            step=5.0,
        )
        f, g, h = st.columns(3)
        workers = f.number_input(
            "Solver workers",
            min_value=1,
            max_value=config.MAX_WORKERS,
            value=settings.workers,
            help="1 worker favours reproducibility; more workers can be faster.",
        )
        seed = g.number_input("Random seed", min_value=0, value=settings.random_seed)
        hard_due = h.checkbox(
            "Enforce due dates as hard constraints",
            value=settings.enforce_due_dates,
            help="If enabled and unreachable the model becomes infeasible.",
        )
        changeovers = st.checkbox("Model sequence-dependent changeovers", value=settings.changeover_enabled)
        st.caption(
            "Time unit: minutes (fixed). One scheduling minute equals one clock minute; shifts and breaks must be modelled as machine availability."
        )
        if st.form_submit_button("Save Settings", type="primary"):
            try:
                new = build_record(
                    PlanningSettings,
                    origin=datetime.combine(origin_date, origin_time),
                    horizon_end=int(horizon),
                    objective=objective,
                    enforce_due_dates=hard_due,
                    changeover_enabled=changeovers,
                    time_limit_seconds=float(limit),
                    workers=int(workers),
                    random_seed=int(seed),
                    dataset_label=settings.dataset_label,
                )
                svc.save_settings(new)
                flash(
                    "success",
                    "Settings saved. Schedules generated with different settings are now marked out of date.",
                )
                st.rerun()
            except TextileOptimizerError as exc:
                for m in getattr(exc, "messages", [str(exc)]):
                    st.error(m)


def _changeover_editor(svc) -> None:
    with (
        st.expander("Changeover matrix (minutes between consecutive operations on a machine)"),
        st.form("changeover_form"),
    ):
        st.caption(
            "Rows are explicit: missing transitions are never assumed to be zero. The first operation on a machine needs no setup. "
            "Transitions must satisfy the triangle inequality. Setup time is a gap between operations; it is not required to fall inside availability windows."
        )
        rules = svc.repo.list_changeover_rules()
        df = pd.DataFrame(
            {
                "from_category": [r.from_category for r in rules],
                "to_category": [r.to_category for r in rules],
                "minutes": pd.array([r.minutes for r in rules], dtype="Int64"),
            }
        )
        edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="co_editor")
        if st.form_submit_button("Save Changeover Rules"):
            try:
                new = [
                    ChangeoverRule(
                        from_category=str(r.from_category),
                        to_category=str(r.to_category),
                        minutes=int(r.minutes),
                    )
                    for r in edited.itertuples()
                    if not pd.isna(r.from_category)
                ]
                svc.save_changeover_rules(new)
                flash("success", "Changeover rules saved.")
                st.rerun()
            except (TextileOptimizerError, ValueError) as exc:
                for m in getattr(exc, "messages", [str(exc)]):
                    st.error(m)


def render() -> None:
    page_header("Schedule", "Configure, validate, generate and inspect production schedules.")
    show_flash()
    svc = get_service()
    data = svc.load_data()
    settings = data.settings

    if settings.dataset_label:
        st.caption(f"Dataset: {settings.dataset_label}")
    st.markdown(
        f"**Active objective:** {OBJECTIVE_LABELS[settings.objective]} | horizon 0-{settings.horizon_end} min "
        f"from {settings.origin:%Y-%m-%d %H:%M} | time limit {settings.time_limit_seconds:g}s | "
        f"changeovers {'modelled' if settings.changeover_enabled else 'NOT modelled'} | "
        f"due dates {'hard' if settings.enforce_due_dates else 'soft (optimization targets)'}"
    )
    _settings_form(svc, settings)
    _changeover_editor(svc)

    st.subheader("Pre-scheduling check")
    c = st.columns(4)
    c[0].metric("Orders (ready)", sum(1 for o in data.orders if o.status.value == "ready"))
    c[1].metric("Operations", len(data.operations))
    c[2].metric("Machines", len(data.machines))
    report = svc.validate_inputs()
    c[3].metric("Blocking errors", len(report.errors))
    if st.button("Validate Inputs"):
        st.session_state["_show_validation"] = True
    if st.session_state.get("_show_validation") or report.errors:
        show_issues(report)
        if report.passed:
            st.success("Inputs passed validation. This does not mean a feasible schedule exists.")

    st.subheader("Generate")
    running = st.session_state.get("_running", False)
    if st.button(
        "Generate Schedule",
        type="primary",
        disabled=running or not report.passed,
        help="Runs the solver once, then validates the result independently.",
    ):
        st.session_state["_running"] = True
        try:
            with st.spinner(
                "Solving (up to the configured time limit)... no progress percentage is available."
            ):
                result = svc.run_schedule()
            st.session_state["_last_result"] = (
                result.outcome,
                result.message,
                result.run.run_id if result.run else None,
            )
        except RunInProgressError as exc:
            st.warning(str(exc))
        except TextileOptimizerError as exc:
            st.error(f"{exc}")
        finally:
            st.session_state["_running"] = False
    last = st.session_state.get("_last_result")
    if last:
        outcome, message, _ = last
        (st.success if outcome == "ACCEPTED" else st.error)(message)

    st.subheader("Results")
    runs = svc.repo.list_runs()
    if not runs:
        st.info("No schedule has been generated yet. Validate the inputs, then select Generate Schedule.")
        return
    latest_ok = svc.repo.latest_accepted_run()
    options = {f"Run {r.run_id} - {r.created_at} - {r.outcome}": r.run_id for r in runs}
    default_idx = 0
    if latest_ok is not None:
        default_idx = list(options.values()).index(latest_ok.run_id)
    label = st.selectbox("Run to inspect (newest first)", list(options), index=default_idx)
    run = svc.repo.get_run(options[label])
    stale = svc.is_stale(run)
    show_run_header(run, stale)
    show_run_details(run)
    show_schedule(run)
    if run.accepted:
        st.download_button(
            "Download schedule (CSV)",
            schedule_csv(run, stale),
            file_name=f"schedule_run_{run.run_id}.csv",
            mime="text/csv",
        )
