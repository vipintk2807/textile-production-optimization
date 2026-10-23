"""Schedule metrics, computed from a snapshot and a list of scheduled operations.

All functions are pure and use integer minutes relative to the planning origin.

Definitions (textile_scheduling_rules 12, 13, 19):

* completion  C_o = latest end time of the order's terminal operations
* lateness    L_o = C_o - Q_o            (signed)
* tardiness   T_o = max(0, C_o - Q_o)
* makespan    C_max = latest end time of any scheduled operation
* utilization U_m = P_m / A_m * 100 %    P_m = scheduled *processing* time on the machine
              (changeover time excluded), A_m = available production time in the same
              horizon [0, horizon_end]; reported as ``None`` (unavailable) when A_m == 0.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from ..domain.intervals import clip, total_length
from ..domain.snapshot import ProblemSnapshot, ScheduledOperation


def completion_times(snapshot: ProblemSnapshot, assignments: Sequence[ScheduledOperation]) -> dict[str, int]:
    """Order completion from the *final required* operations only.

    An order is omitted when any of its terminal operations is unscheduled - no completion
    time is invented for partially scheduled orders.
    """
    end_by_op: dict[str, int] = {}
    for a in assignments:
        end_by_op[a.operation_id] = max(a.end, end_by_op.get(a.operation_id, a.end))
    result: dict[str, int] = {}
    for order in snapshot.orders:
        terminals = snapshot.terminal_operations(order.order_id)
        if terminals and all(t.operation_id in end_by_op for t in terminals):
            result[order.order_id] = max(end_by_op[t.operation_id] for t in terminals)
    return result


def lateness(snapshot: ProblemSnapshot, completion: dict[str, int]) -> dict[str, int]:
    return {
        o.order_id: completion[o.order_id] - o.due_time for o in snapshot.orders if o.order_id in completion
    }


def tardiness(snapshot: ProblemSnapshot, completion: dict[str, int]) -> dict[str, int]:
    return {oid: max(0, value) for oid, value in lateness(snapshot, completion).items()}


def makespan(assignments: Sequence[ScheduledOperation]) -> int | None:
    return max((a.end for a in assignments), default=None)


def total_tardiness(tardy: dict[str, int]) -> int:
    return sum(tardy.values())


def weighted_tardiness(snapshot: ProblemSnapshot, tardy: dict[str, int]) -> int | None:
    """Sum of w_o * T_o; ``None`` when a scheduled order has no configured weight."""
    total = 0
    for order in snapshot.orders:
        if order.order_id not in tardy:
            continue
        if order.weight is None:
            return None
        total += order.weight * tardy[order.order_id]
    return total


def objective_value(snapshot: ProblemSnapshot, assignments: Sequence[ScheduledOperation]) -> int | None:
    """Value of the snapshot's configured objective for these assignments."""
    if snapshot.objective == "makespan":
        return makespan(assignments)
    tardy = tardiness(snapshot, completion_times(snapshot, assignments))
    if snapshot.objective == "total_tardiness":
        return total_tardiness(tardy)
    if snapshot.objective == "weighted_tardiness":
        return weighted_tardiness(snapshot, tardy)
    return None


@dataclass(frozen=True)
class MachineUtilization:
    machine_id: str
    processing_minutes: int
    available_minutes: int
    idle_minutes: int  # available - processing (includes any changeover time)
    utilization_pct: float | None  # None = unavailable (A_m == 0)


def machine_utilization(
    snapshot: ProblemSnapshot, assignments: Sequence[ScheduledOperation]
) -> list[MachineUtilization]:
    per_machine: dict[str, list[ScheduledOperation]] = defaultdict(list)
    for a in assignments:
        per_machine[a.machine_id].append(a)
    rows: list[MachineUtilization] = []
    for machine in sorted(snapshot.machines, key=lambda m: m.machine_id):
        available = total_length(
            w for w in (clip(w, 0, snapshot.horizon_end) for w in machine.windows) if w is not None
        )
        processing = total_length(
            c
            for c in (
                clip((a.start, a.end), 0, snapshot.horizon_end) for a in per_machine[machine.machine_id]
            )
            if c is not None
        )
        pct = round(100.0 * processing / available, 2) if available > 0 else None
        rows.append(
            MachineUtilization(machine.machine_id, processing, available, available - processing, pct)
        )
    return rows


def changeover_minutes(snapshot: ProblemSnapshot, assignments: Sequence[ScheduledOperation]) -> int | None:
    """Total changeover time between consecutive operations on each machine.

    ``None`` when changeovers are not modelled (never reported as 0 in that case).
    """
    if not snapshot.changeover_enabled:
        return None
    ops = snapshot.operation_map()
    per_machine: dict[str, list[ScheduledOperation]] = defaultdict(list)
    for a in assignments:
        per_machine[a.machine_id].append(a)
    total = 0
    for items in per_machine.values():
        items.sort(key=lambda a: (a.start, a.end))
        for prev, nxt in zip(items, items[1:], strict=False):
            if prev.operation_id in ops and nxt.operation_id in ops:
                total += snapshot.setup_minutes(ops[prev.operation_id], ops[nxt.operation_id])
    return total


def schedule_metrics(snapshot: ProblemSnapshot, assignments: Sequence[ScheduledOperation]) -> dict:
    """All persisted/reported metrics as a JSON-serialisable dict."""
    completion = completion_times(snapshot, assignments)
    tardy = tardiness(snapshot, completion)
    late = lateness(snapshot, completion)
    orders = []
    for order in snapshot.orders:
        oid = order.order_id
        orders.append(
            {
                "order_id": oid,
                "due_time": order.due_time,
                "completion_time": completion.get(oid),
                "lateness": late.get(oid),
                "tardiness": tardy.get(oid),
                "is_late": (tardy[oid] > 0) if oid in tardy else None,
                "operation_count": len(snapshot.operations_of(oid)),
                "weight": order.weight,
            }
        )
    util = machine_utilization(snapshot, assignments)
    return {
        "objective": snapshot.objective,
        "objective_value": objective_value(snapshot, assignments),
        "makespan": makespan(assignments),
        "total_tardiness": total_tardiness(tardy),
        "weighted_tardiness": weighted_tardiness(snapshot, tardy),
        "late_orders": sum(1 for v in tardy.values() if v > 0),
        "scheduled_orders": len(completion),
        "scheduled_operations": len(assignments),
        "total_processing_minutes": sum(a.end - a.start for a in assignments),
        "changeover_minutes": changeover_minutes(snapshot, assignments),
        "orders": orders,
        "machines": [asdict(u) for u in util],
        "utilization_definition": (
            "U_m = scheduled processing minutes / available production minutes within "
            f"[0, {snapshot.horizon_end}); changeover time is excluded from processing time."
        ),
    }
