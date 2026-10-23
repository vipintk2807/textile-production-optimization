"""Production Orders page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ... import config
from ...domain.models import OrderRecord, OrderStatus
from ...domain.timeutil import to_datetime
from ...errors import TextileOptimizerError
from ...services.planning_service import build_record
from ..components import empty_state, page_header
from ..context import flash, get_service, show_flash

NEW = "(new order)"


def render() -> None:
    page_header("Production Orders", "Manage orders, due times, quantities and priorities.")
    show_flash()
    svc = get_service()
    settings = svc.repo.get_settings()
    orders = svc.repo.list_orders()
    ops = svc.repo.list_operations()
    op_count = {o.order_id: sum(1 for p in ops if p.order_id == o.order_id) for o in orders}

    st.caption(
        f"Times are whole minutes from the planning origin {settings.origin:%Y-%m-%d %H:%M} "
        f"(horizon end {settings.horizon_end}). Quantity units are never converted."
    )
    if not orders:
        empty_state("No orders yet. Use the form below to create the first production order.")
    else:
        c1, c2, c3 = st.columns([2, 1, 1])
        text = c1.text_input("Filter by order ID / product", key="ord_filter")
        status = c2.selectbox("Status", ["all", *[s.value for s in OrderStatus]], key="ord_status")
        prio = c3.selectbox("Priority", ["all", 1, 2, 3, 4, 5], key="ord_prio")
        rows = []
        for o in orders:
            if text and text.lower() not in f"{o.order_id} {o.product_code}".lower():
                continue
            if status != "all" and o.status.value != status:
                continue
            if prio != "all" and o.priority != prio:
                continue
            rows.append(
                {
                    "Order ID": o.order_id,
                    "Product": o.product_code,
                    "Description": o.description,
                    "Quantity": f"{o.quantity:g} {o.quantity_unit}",
                    "Release (min)": o.release_time,
                    "Due (min)": o.due_time,
                    "Due (calendar)": f"{to_datetime(o.due_time, settings.origin):%Y-%m-%d %H:%M}",
                    "Priority": o.priority if o.priority is not None else "-",
                    "Weight": o.weight if o.weight is not None else "-",
                    "Operations": op_count[o.order_id],
                    "Status": o.status.value,
                    "Configuration": "Incomplete: no operations"
                    if op_count[o.order_id] == 0
                    else "Has operations",
                    "Data": "synthetic" if o.is_synthetic else "user",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Create or edit an order")
    choice = st.selectbox("Order", [NEW, *[o.order_id for o in orders]], key="ord_select")
    current = next((o for o in orders if o.order_id == choice), None)
    key = f"order_form_{choice}"
    with st.form(key):
        st.markdown("**Order identification**")
        a, b = st.columns(2)
        order_id = a.text_input(
            "Order ID *", value=current.order_id if current else "", disabled=current is not None
        )
        product = b.text_input("Product code *", value=current.product_code if current else "")
        description = st.text_input("Description", value=current.description if current else "")
        st.markdown("**Production requirements**")
        c, d = st.columns(2)
        quantity = c.number_input(
            "Quantity *", min_value=0.0, value=float(current.quantity) if current else 1.0, step=1.0
        )
        unit = d.selectbox(
            "Quantity unit *",
            config.QUANTITY_UNITS,
            index=config.QUANTITY_UNITS.index(current.quantity_unit) if current else 0,
        )
        st.markdown("**Scheduling requirements** (whole minutes from the planning origin)")
        e, f, g, h = st.columns(4)
        release = e.number_input(
            "Release time (min) *", min_value=0, value=current.release_time if current else 0, step=30
        )
        due = f.number_input(
            "Due time (min) *", min_value=0, value=current.due_time if current else 1440, step=30
        )
        priority = g.selectbox(
            "Priority (1 low - 5 high)",
            [None, 1, 2, 3, 4, 5],
            index=([None, 1, 2, 3, 4, 5].index(current.priority) if current else 0),
            format_func=lambda v: "not set" if v is None else str(v),
        )
        weight = h.number_input(
            "Weight (weighted tardiness)",
            min_value=-1,
            value=(current.weight if current and current.weight is not None else -1),
            help="Non-negative integer used only by the weighted-tardiness objective. -1 = not set.",
        )
        st.caption(f"Due time as calendar: {to_datetime(int(due), settings.origin):%Y-%m-%d %H:%M}")
        st.markdown("**Status and notes**")
        i, j = st.columns([1, 3])
        status_val = i.selectbox(
            "Status *",
            [s.value for s in OrderStatus],
            index=[s.value for s in OrderStatus].index(current.status.value) if current else 0,
            help="Only 'ready' orders are scheduled.",
        )
        notes = j.text_area("Notes", value=current.notes if current else "", height=70)
        submitted = st.form_submit_button("Save Order", type="primary")
    if submitted:
        try:
            record = build_record(
                OrderRecord,
                order_id=order_id if not current else current.order_id,
                product_code=product,
                description=description,
                quantity=quantity,
                quantity_unit=unit,
                release_time=int(release),
                due_time=int(due),
                priority=priority,
                weight=None if weight < 0 else int(weight),
                status=status_val,
                notes=notes,
                is_synthetic=current.is_synthetic if current else False,
            )
            svc.save_order(record, is_new=current is None)
            flash(
                "success",
                f"Production order {record.order_id} saved. (Saving data does not run or validate a schedule.)",
            )
            st.rerun()
        except TextileOptimizerError as exc:
            for m in getattr(exc, "messages", [str(exc)]):
                st.error(m)

    if current:
        with st.expander("Delete this order"):
            n = op_count.get(current.order_id, 0)
            st.warning(
                f"Deleting {current.order_id} also deletes its {n} operation(s) and marks schedules that used it as out of date."
            )
            confirm = st.checkbox(
                f"I confirm deleting order {current.order_id}", key=f"ord_del_{current.order_id}"
            )
            if st.button("Delete Order", disabled=not confirm, key="ord_del_btn"):
                try:
                    removed = svc.delete_order(current.order_id)
                    flash("success", f"Order {current.order_id} and {removed} operation(s) deleted.")
                    st.rerun()
                except TextileOptimizerError as exc:
                    st.error(str(exc))
