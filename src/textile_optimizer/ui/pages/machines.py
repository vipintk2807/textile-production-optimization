"""Machines page: capabilities, availability windows and downtime."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ...domain.models import IntervalRecord, MachineRecord, MachineStatus
from ...errors import TextileOptimizerError
from ...services.planning_service import build_record
from ..components import empty_state, page_header
from ..context import flash, get_service, show_flash

NEW = "(new machine)"


def _intervals_from(df: pd.DataFrame) -> list[IntervalRecord]:
    out = []
    for _, row in df.iterrows():
        if pd.isna(row.get("start")) and pd.isna(row.get("end")):
            continue
        out.append(IntervalRecord(start=int(row["start"]), end=int(row["end"])))
    return out


def _frame(intervals) -> pd.DataFrame:
    return pd.DataFrame(
        {"start": [i.start for i in intervals], "end": [i.end for i in intervals]}, dtype="Int64"
    )


def render() -> None:
    page_header("Machines", "Configure capabilities, availability windows and planned downtime.")
    show_flash()
    svc = get_service()
    machines = svc.repo.list_machines()
    ops = svc.repo.list_operations()
    st.caption(
        "Each machine is a single-capacity resource. Intervals are half-open [start, end) in whole "
        "minutes from the planning origin. Unknown availability is never treated as unlimited."
    )
    if not machines:
        empty_state(
            "No machines yet. Create a machine with at least one capability and one availability window."
        )
    else:
        rows = []
        for m in machines:
            eligible = sum(1 for o in ops if any(e.machine_id == m.machine_id for e in o.eligible_machines))
            complete = bool(m.availability)
            rows.append(
                {
                    "Machine ID": m.machine_id,
                    "Name": m.machine_name,
                    "Type": m.machine_type,
                    "Capabilities": ", ".join(m.supported_processes),
                    "Status": m.status.value,
                    "Availability windows": len(m.availability),
                    "Downtime intervals": len(m.downtime),
                    "Eligible operations": eligible,
                    "Configuration": "Complete" if complete else "Incomplete: no availability windows",
                    "Data": "synthetic" if m.is_synthetic else "user",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Create or edit a machine")
    choice = st.selectbox("Machine", [NEW, *[m.machine_id for m in machines]], key="mac_select")
    current = next((m for m in machines if m.machine_id == choice), None)
    with st.form(f"machine_form_{choice}"):
        a, b, c = st.columns(3)
        machine_id = a.text_input(
            "Machine ID *", value=current.machine_id if current else "", disabled=current is not None
        )
        name = b.text_input("Machine name *", value=current.machine_name if current else "")
        mtype = c.text_input("Machine type *", value=current.machine_type if current else "")
        caps = st.text_input(
            "Supported processes (comma-separated) *",
            value=", ".join(current.supported_processes) if current else "",
            help="Operation names must match one of these processes exactly (e.g. knitting, dyeing).",
        )
        status = st.selectbox(
            "Status",
            [s.value for s in MachineStatus],
            index=[s.value for s in MachineStatus].index(current.status.value) if current else 0,
            help="Inactive machines are never assigned operations.",
        )
        left, right = st.columns(2)
        left.markdown("**Availability windows** (minutes)")
        avail_df = left.data_editor(
            _frame(current.availability if current else []),
            num_rows="dynamic",
            key=f"avail_{choice}",
            use_container_width=True,
        )
        right.markdown("**Downtime intervals** (minutes)")
        down_df = right.data_editor(
            _frame(current.downtime if current else []),
            num_rows="dynamic",
            key=f"down_{choice}",
            use_container_width=True,
        )
        notes = st.text_area("Notes", value=current.notes if current else "", height=60)
        submitted = st.form_submit_button("Save Machine", type="primary")
    if submitted:
        try:
            record = build_record(
                MachineRecord,
                machine_id=machine_id if not current else current.machine_id,
                machine_name=name,
                machine_type=mtype,
                supported_processes=[p for p in caps.split(",")],
                status=status,
                notes=notes,
                availability=_intervals_from(avail_df),
                downtime=_intervals_from(down_df),
                is_synthetic=current.is_synthetic if current else False,
            )
            svc.save_machine(record, is_new=current is None)
            flash("success", f"Machine {record.machine_id} saved.")
            st.rerun()
        except (TextileOptimizerError, ValueError, TypeError) as exc:
            for m in getattr(exc, "messages", [str(exc)]):
                st.error(m)

    if current:
        with st.expander("Delete this machine"):
            used = svc.repo.operations_using_machine(current.machine_id)
            if used:
                st.warning(
                    f"{current.machine_id} is an eligible machine of {len(used)} operation(s): "
                    f"{', '.join(used[:10])}. Remove it from them first, or set the machine to inactive."
                )
            confirm = st.checkbox(
                f"I confirm deleting machine {current.machine_id}", key=f"mac_del_{current.machine_id}"
            )
            if st.button("Delete Machine", disabled=not confirm, key="mac_del_btn"):
                try:
                    svc.delete_machine(current.machine_id)
                    flash("success", f"Machine {current.machine_id} deleted.")
                    st.rerun()
                except TextileOptimizerError as exc:
                    st.error(str(exc))
