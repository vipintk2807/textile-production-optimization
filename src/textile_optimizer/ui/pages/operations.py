"""Operations page: routing, durations, eligible machines and predecessors."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ...domain.graph import find_cycle
from ...domain.models import EligibleMachine, OperationRecord, OperationStatus
from ...errors import TextileOptimizerError
from ...services.planning_service import build_record
from ..components import empty_state, page_header
from ..context import flash, get_service, show_flash

NEW = "(new operation)"


def render() -> None:
    page_header(
        "Operations", "Define the operations of each order: durations, eligible machines and predecessors."
    )
    show_flash()
    svc = get_service()
    orders = svc.repo.list_orders()
    machines = svc.repo.list_machines()
    ops = svc.repo.list_operations()
    machine_ids = {m.machine_id for m in machines}
    st.caption(
        "Durations are positive whole minutes. Predecessors must belong to the same order (finish-to-start). "
        "Machine-specific durations override the default duration for that machine only."
    )

    if not ops:
        empty_state(
            "No operations yet. Create orders and machines first, then define each order's operations."
        )
    else:
        f1, f2 = st.columns(2)
        order_filter = f1.selectbox(
            "Filter by order", ["all", *[o.order_id for o in orders]], key="op_f_order"
        )
        machine_filter = f2.selectbox(
            "Filter by eligible machine", ["all", *sorted(machine_ids)], key="op_f_mac"
        )
        rows = []
        for o in ops:
            if order_filter != "all" and o.order_id != order_filter:
                continue
            if machine_filter != "all" and machine_filter not in [e.machine_id for e in o.eligible_machines]:
                continue
            problems = []
            if not o.eligible_machines:
                problems.append("no eligible machine")
            if any(p not in {x.operation_id for x in ops} for p in o.predecessors):
                problems.append("missing predecessor")
            rows.append(
                {
                    "Operation ID": o.operation_id,
                    "Order": o.order_id,
                    "Name / process": o.operation_name,
                    "Seq": o.sequence,
                    "Duration (min)": o.processing_duration,
                    "Duration basis": "estimate" if o.duration_is_estimate else "measured/validated",
                    "Eligible machines": ", ".join(
                        e.machine_id + (f" ({e.duration_override} min)" if e.duration_override else "")
                        for e in o.eligible_machines
                    ),
                    "Predecessors": ", ".join(o.predecessors) or "-",
                    "Changeover category": o.changeover_category or "-",
                    "Status": o.status.value,
                    "Configuration": "Incomplete: " + ", ".join(problems) if problems else "OK",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        graph = {o.operation_id: list(o.predecessors) for o in ops}
        if st.button("Validate Operation Sequence"):
            cycle = find_cycle(graph.keys(), graph)
            missing = sorted({p for o in ops for p in o.predecessors if p not in graph})
            if cycle:
                st.error("Dependency cycle: " + " -> ".join(cycle))
            elif missing:
                st.error("Missing predecessor operations: " + ", ".join(missing))
            else:
                st.success("Operation dependencies are valid and acyclic.")

    st.subheader("Create or edit an operation")
    if not orders or not machines:
        empty_state("Create at least one order and one machine before defining operations.")
        return
    choice = st.selectbox("Operation", [NEW, *[o.operation_id for o in ops]], key="op_select")
    current = next((o for o in ops if o.operation_id == choice), None)
    categories = sorted({p for m in machines for p in m.supported_processes})
    with st.form(f"operation_form_{choice}"):
        a, b, c = st.columns(3)
        op_id = a.text_input(
            "Operation ID *", value=current.operation_id if current else "", disabled=current is not None
        )
        order_id = b.selectbox(
            "Parent order *",
            [o.order_id for o in orders],
            index=[o.order_id for o in orders].index(current.order_id)
            if current and current.order_id in [o.order_id for o in orders]
            else 0,
        )
        name = c.selectbox(
            "Operation / process *",
            categories,
            index=categories.index(current.operation_name)
            if current and current.operation_name in categories
            else 0,
            help="Must match a capability of the eligible machines.",
        )
        d, e, f = st.columns(3)
        duration = d.number_input(
            "Default duration (min) *",
            min_value=1,
            value=current.processing_duration if current else 60,
            step=5,
        )
        sequence = e.number_input("Sequence", min_value=0, value=current.sequence if current else 1)
        status = f.selectbox(
            "Status",
            [s.value for s in OperationStatus],
            index=[s.value for s in OperationStatus].index(current.status.value) if current else 0,
        )
        g, h = st.columns(2)
        estimate = g.checkbox(
            "Duration is an estimate", value=current.duration_is_estimate if current else True
        )
        source = h.text_input(
            "Duration source / assumption", value=current.duration_source if current else ""
        )
        eligible_default = (
            [e.machine_id for e in current.eligible_machines if e.machine_id in machine_ids]
            if current
            else []
        )
        eligible = st.multiselect("Eligible machines *", sorted(machine_ids), default=eligible_default)
        overrides_text = st.text_input(
            "Machine-specific durations (optional)",
            help="Format: MACHINE-ID=minutes, comma-separated. Example: DYE-02=240",
            value=", ".join(
                f"{e.machine_id}={e.duration_override}"
                for e in current.eligible_machines
                if e.duration_override
            )
            if current
            else "",
        )
        other_ops = [
            o.operation_id for o in ops if o.operation_id != (current.operation_id if current else None)
        ]
        preds = st.multiselect(
            "Predecessor operations",
            other_ops,
            default=[p for p in (current.predecessors if current else []) if p in other_ops],
        )
        category = st.text_input(
            "Changeover category (used when changeovers are enabled)",
            value=current.changeover_category or "" if current else "",
        )
        notes = st.text_area("Notes", value=current.notes if current else "", height=60)
        submitted = st.form_submit_button("Save Operation", type="primary")
    if submitted:
        try:
            overrides: dict[str, int] = {}
            for part in [p.strip() for p in overrides_text.split(",") if p.strip()]:
                if "=" not in part:
                    raise ValueError(f"Machine-specific duration '{part}' must look like MACHINE-ID=minutes.")
                k, v = part.split("=", 1)
                overrides[k.strip()] = int(v)
            unknown = set(overrides) - set(eligible)
            if unknown:
                raise ValueError(
                    f"Machine-specific durations given for non-selected machines: {', '.join(sorted(unknown))}."
                )
            record = build_record(
                OperationRecord,
                operation_id=op_id if not current else current.operation_id,
                order_id=order_id,
                operation_name=name,
                sequence=int(sequence),
                processing_duration=int(duration),
                duration_is_estimate=estimate,
                duration_source=source,
                eligible_machines=[
                    EligibleMachine(machine_id=m, duration_override=overrides.get(m)) for m in eligible
                ],
                predecessors=preds,
                changeover_category=category or None,
                status=status,
                notes=notes,
                is_synthetic=current.is_synthetic if current else False,
            )
            svc.save_operation(record, is_new=current is None)
            flash("success", f"Operation {record.operation_id} saved.")
            st.rerun()
        except TextileOptimizerError as exc:
            for m in getattr(exc, "messages", [str(exc)]):
                st.error(m)
        except ValueError as exc:
            st.error(str(exc))

    if current:
        with st.expander("Delete this operation"):
            succ = svc.repo.successors_of(current.operation_id)
            if succ:
                st.warning(
                    f"{current.operation_id} is a predecessor of {', '.join(succ)}; remove those dependencies first."
                )
            confirm = st.checkbox(
                f"I confirm deleting operation {current.operation_id}", key=f"op_del_{current.operation_id}"
            )
            if st.button("Delete Operation", disabled=not confirm, key="op_del_btn"):
                try:
                    svc.delete_operation(current.operation_id)
                    flash("success", f"Operation {current.operation_id} deleted.")
                    st.rerun()
                except TextileOptimizerError as exc:
                    st.error(str(exc))
