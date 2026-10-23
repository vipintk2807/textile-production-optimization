"""CSV export built from the *stored* run (same data as the schedule table and timeline)."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from ..domain.timeutil import to_datetime
from ..errors import ExportError
from ..persistence.repository import StoredRun


def run_status_label(run: StoredRun, stale: bool) -> str:
    """Single honest label for exports: what the schedule is and whether it is current."""
    if not run.accepted:
        return f"NOT_ACCEPTED_{run.outcome}"
    return "VALIDATED_STALE_HISTORICAL" if stale else "VALIDATED_CURRENT"


def _origin(run: StoredRun) -> datetime:
    return datetime.fromisoformat(run.snapshot.origin_iso)


def schedule_rows(run: StoredRun, stale: bool) -> list[dict]:
    """One row per scheduled operation with order completion and tardiness."""
    if not run.assignments:
        raise ExportError("This run has no scheduled operations to export.")
    metrics_by_order = {o["order_id"]: o for o in (run.metrics or {}).get("orders", [])}
    origin = _origin(run)
    orders = run.snapshot.order_map()
    label = run_status_label(run, stale)
    rows = []
    for a in sorted(run.assignments, key=lambda x: (x.machine_id, x.start, x.operation_id)):
        om = metrics_by_order.get(a.order_id, {})
        order = orders.get(a.order_id)
        rows.append(
            {
                "run_id": run.run_id,
                "run_status": label,
                "solver_status": run.solver_status or "",
                "objective": run.objective,
                "input_fingerprint": run.input_fingerprint,
                "order_id": a.order_id,
                "operation_id": a.operation_id,
                "machine_id": a.machine_id,
                "start_min": a.start,
                "end_min": a.end,
                "duration_min": a.duration,
                "start_datetime": f"{to_datetime(a.start, origin):%Y-%m-%d %H:%M}",
                "end_datetime": f"{to_datetime(a.end, origin):%Y-%m-%d %H:%M}",
                "order_due_min": order.due_time if order else "",
                "order_completion_min": om.get("completion_time", ""),
                "tardiness_min": om.get("tardiness", ""),
                "late": ("" if om.get("is_late") is None else ("yes" if om["is_late"] else "no")),
            }
        )
    return rows


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        raise ExportError("There is no data to export.")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def schedule_csv(run: StoredRun, stale: bool) -> str:
    return _to_csv(schedule_rows(run, stale))


def order_performance_rows(run: StoredRun) -> list[dict]:
    if run.metrics is None:
        raise ExportError("Order metrics exist only for accepted (validated) schedules.")
    return [
        {
            "run_id": run.run_id,
            "order_id": o["order_id"],
            "due_min": o["due_time"],
            "completion_min": "" if o["completion_time"] is None else o["completion_time"],
            "lateness_min": "" if o["lateness"] is None else o["lateness"],
            "tardiness_min": "" if o["tardiness"] is None else o["tardiness"],
            "late": "" if o["is_late"] is None else ("yes" if o["is_late"] else "no"),
            "operations": o["operation_count"],
        }
        for o in run.metrics["orders"]
    ]


def machine_utilization_rows(run: StoredRun) -> list[dict]:
    if run.metrics is None:
        raise ExportError("Utilization exists only for accepted (validated) schedules.")
    return [
        {
            "run_id": run.run_id,
            "machine_id": m["machine_id"],
            "processing_min": m["processing_minutes"],
            "available_min": m["available_minutes"],
            "idle_min": m["idle_minutes"],
            "utilization_pct": "unavailable" if m["utilization_pct"] is None else m["utilization_pct"],
        }
        for m in run.metrics["machines"]
    ]


def order_performance_csv(run: StoredRun) -> str:
    return _to_csv(order_performance_rows(run))


def machine_utilization_csv(run: StoredRun) -> str:
    return _to_csv(machine_utilization_rows(run))
