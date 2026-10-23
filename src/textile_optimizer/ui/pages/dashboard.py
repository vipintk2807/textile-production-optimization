"""Dashboard page: counts, latest schedule status, machine loading, shortcuts."""

from __future__ import annotations

import streamlit as st

from ... import config
from ...errors import TextileOptimizerError
from ...persistence.db import backup_database
from ...services.sample_data import SAMPLE_LABEL, load_sample_data
from ..components import empty_state, page_header, show_badges
from ..context import flash, get_service, go_to, show_flash
from ..run_view import show_run_header


def render() -> None:
    page_header("Dashboard", "Planning overview, latest schedule status and machine loading.")
    show_flash()
    svc = get_service()
    counts = svc.repo.counts()
    settings = svc.repo.get_settings()
    if settings.dataset_label:
        show_badges(("Synthetic sample data loaded", "grey"))
        st.caption(settings.dataset_label)

    run = svc.repo.latest_accepted_run()
    stale = svc.is_stale(run) if run else False
    m = run.metrics if run else None
    c = st.columns(4)
    c[0].metric("Production orders", counts["orders"])
    c[1].metric("Operations", counts["operations"])
    c[2].metric("Machines", counts["machines"])
    c[3].metric("Scheduled operations", m["scheduled_operations"] if m and not stale else "unavailable")
    d = st.columns(3)
    d[0].metric("Late orders", m["late_orders"] if m and not stale else "unavailable")
    d[1].metric("Total tardiness (min)", m["total_tardiness"] if m and not stale else "unavailable")
    d[2].metric("Latest schedule", "none" if run is None else ("out of date" if stale else "current"))

    if counts["orders"] == 0:
        empty_state(
            "No production orders yet. Start by configuring Machines, then create Production Orders and their Operations."
        )
    else:
        report = svc.validate_inputs()
        if report.errors:
            st.warning(
                f"The saved data has {len(report.errors)} blocking error(s); open the Schedule page for details."
            )

    if run is None:
        empty_state("No validated schedule yet. Open the Schedule page to validate inputs and generate one.")
    else:
        st.subheader("Latest validated schedule")
        show_run_header(run, stale)
        if not stale:
            st.markdown(
                f"**Machine utilization** (processing / available within 0-{run.snapshot.horizon_end} min; changeover time excluded)"
            )
            for mu in m["machines"]:
                pct = mu["utilization_pct"]
                st.write(
                    f"{mu['machine_id']}: "
                    + ("unavailable (no available time)" if pct is None else f"{pct:.1f}%")
                )
                if pct is not None:
                    st.progress(min(1.0, pct / 100.0))
        else:
            st.caption("Utilization is hidden because the schedule is out of date.")

    st.subheader("Shortcuts")
    b = st.columns(6)
    for col, (label, key) in zip(
        b,
        [
            ("Manage Orders", "orders"),
            ("Manage Machines", "machines"),
            ("Define Operations", "operations"),
            ("Generate Schedule", "schedule"),
            ("View Latest Schedule", "schedule"),
            ("View Reports", "reports"),
        ],
        strict=True,
    ):
        if col.button(label, key=f"dash_{label}"):
            go_to(key)

    with st.expander("Data management"):
        st.write(f"Database file: `{config.db_path()}`")
        if st.button("Create database backup"):
            try:
                from datetime import datetime

                target = config.backup_dir() / f"backup_{datetime.now():%Y%m%d_%H%M%S}.db"
                backup_database(config.db_path(), target)
                st.success(f"Backup created: {target}")
            except TextileOptimizerError as exc:
                st.error(str(exc))
        st.markdown(f"**Synthetic sample data** - {SAMPLE_LABEL}. Loads only into an empty database.")
        if st.button(
            "Load synthetic sample data",
            disabled=any(counts[k] for k in ("orders", "machines", "operations")),
        ):
            try:
                load_sample_data(svc)
                flash("success", "Synthetic sample data loaded.")
                st.rerun()
            except TextileOptimizerError as exc:
                st.error(str(exc))
