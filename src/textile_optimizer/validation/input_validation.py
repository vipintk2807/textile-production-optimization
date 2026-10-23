"""Pre-solver validation of the saved planning data.

Blocking *errors* prevent model construction (the solver never runs on invalid input).
*Warnings* flag valid-but-risky situations; "valid yet infeasible" models are left to the
solver (textile_scheduling_rules 15). Missing values are never replaced silently.
"""

from __future__ import annotations

from collections import Counter

from ..domain.graph import find_cycle, topological_order
from ..domain.intervals import find_overlapping_pairs
from ..domain.models import (
    MachineStatus,
    Objective,
    OperationStatus,
    OrderStatus,
)
from ..domain.snapshot import PlanningData, effective_windows
from .report import ValidationReport


def _duplicates(ids: list[str]) -> list[str]:
    return sorted(i for i, n in Counter(ids).items() if n > 1)


def validate_inputs(data: PlanningData) -> ValidationReport:  # noqa: C901 - one rule per block
    rep = ValidationReport()
    settings = data.settings
    horizon = settings.horizon_end

    # ---- identifiers --------------------------------------------------------------
    for dup in _duplicates([o.order_id for o in data.orders]):
        rep.error("DUP_ORDER", f"Order ID '{dup}' is used more than once.", order_id=dup)
    for dup in _duplicates([m.machine_id for m in data.machines]):
        rep.error("DUP_MACHINE", f"Machine ID '{dup}' is used more than once.", machine_id=dup)
    for dup in _duplicates([o.operation_id for o in data.operations]):
        rep.error("DUP_OPERATION", f"Operation ID '{dup}' is used more than once.", operation_id=dup)

    orders = {o.order_id: o for o in data.orders}
    machines = {m.machine_id: m for m in data.machines}
    ready_ids = {o.order_id for o in data.orders if o.status == OrderStatus.READY}

    # ---- planning horizon -----------------------------------------------------------
    if horizon <= 0:
        rep.error("HORIZON", "The planning horizon end must be greater than 0 minutes.")

    scheduled_ops = [
        op for op in data.operations if op.status == OperationStatus.ACTIVE and op.order_id in ready_ids
    ]
    scheduled_by_id = {op.operation_id: op for op in scheduled_ops}

    # ---- orders -------------------------------------------------------------------------
    if not ready_ids:
        rep.error(
            "NO_ORDERS",
            "There are no orders with status 'ready'. Create an order and set it to 'ready'.",
        )
    draft = [o.order_id for o in data.orders if o.status == OrderStatus.DRAFT]
    if draft:
        rep.warn(
            "DRAFT_EXCLUDED",
            f"{len(draft)} draft order(s) are excluded from scheduling: {', '.join(sorted(draft))}.",
        )
    for oid in sorted(ready_ids):
        order = orders[oid]
        if order.release_time >= horizon:
            rep.error(
                "RELEASE_OUTSIDE_HORIZON",
                f"Order {oid}: release time {order.release_time} is not before the horizon end "
                f"({horizon}). Move the release time or extend the horizon.",
                order_id=oid,
            )
        if not any(op.order_id == oid for op in scheduled_ops):
            rep.error(
                "ORDER_NO_OPERATIONS",
                f"Order {oid} is ready but has no active operations. Define its operations on "
                "the Operations page or set the order to 'draft'.",
                order_id=oid,
            )
        if settings.objective == Objective.WEIGHTED_TARDINESS and order.weight is None:
            rep.error(
                "MISSING_WEIGHT",
                f"Order {oid} has no weight but the weighted-tardiness objective is selected. "
                "Enter a non-negative integer weight (weights are never inferred).",
                order_id=oid,
            )

    # ---- machines / calendars ---------------------------------------------------------
    for mid, machine in sorted(machines.items()):
        label = f"Machine {mid}"
        avail = [i.as_tuple() for i in machine.availability]
        down = [i.as_tuple() for i in machine.downtime]
        for a, b in find_overlapping_pairs(avail):
            rep.error(
                "AVAIL_OVERLAP",
                f"{label}: availability windows {list(a)} and {list(b)} overlap. "
                "Merge or correct them (overlapping calendars are ambiguous).",
                machine_id=mid,
                interval=a,
            )
        for a, b in find_overlapping_pairs(down):
            rep.error(
                "DOWNTIME_OVERLAP",
                f"{label}: downtime intervals {list(a)} and {list(b)} overlap. Merge or correct them.",
                machine_id=mid,
                interval=a,
            )
        for iv in avail:
            if iv[0] >= horizon:
                rep.warn(
                    "AVAIL_OUTSIDE_HORIZON",
                    f"{label}: availability window {list(iv)} starts at/after the horizon end "
                    f"({horizon}) and is ignored.",
                    machine_id=mid,
                    interval=iv,
                )
            elif iv[1] > horizon:
                rep.warn(
                    "AVAIL_CLIPPED",
                    f"{label}: availability window {list(iv)} extends beyond the horizon end "
                    f"({horizon}); it is clipped to the horizon.",
                    machine_id=mid,
                    interval=iv,
                )
        for d in down:
            if not any(d[0] < w[1] and w[0] < d[1] for w in avail):
                rep.warn(
                    "DOWNTIME_NO_EFFECT",
                    f"{label}: downtime {list(d)} does not overlap any availability window.",
                    machine_id=mid,
                    interval=d,
                )

    # ---- operations -------------------------------------------------------------------
    for op in data.operations:
        if op.order_id not in orders:
            rep.error(
                "OP_UNKNOWN_ORDER",
                f"Operation {op.operation_id} references order '{op.order_id}', which does not exist.",
                operation_id=op.operation_id,
                order_id=op.order_id,
            )

    used_machines: set[str] = set()
    for op in sorted(scheduled_ops, key=lambda o: o.operation_id):
        oid = op.operation_id
        refs = {"operation_id": oid, "order_id": op.order_id}
        if not op.eligible_machines:
            rep.error(
                "NO_ELIGIBLE_MACHINE",
                f"Operation {oid} has no eligible machine. Select at least one configured machine "
                "that supports this operation before generating the schedule.",
                **refs,
            )
        active_eligible = []
        for em in op.eligible_machines:
            machine = machines.get(em.machine_id)
            if machine is None:
                rep.error(
                    "UNKNOWN_MACHINE",
                    f"Operation {oid} lists eligible machine '{em.machine_id}', which does not exist.",
                    machine_id=em.machine_id,
                    **refs,
                )
                continue
            if machine.status != MachineStatus.ACTIVE:
                rep.warn(
                    "INACTIVE_MACHINE_IGNORED",
                    f"Operation {oid}: eligible machine {em.machine_id} is inactive and will not be used.",
                    machine_id=em.machine_id,
                    **refs,
                )
                continue
            if op.operation_name not in machine.supported_processes:
                rep.error(
                    "CAPABILITY_MISMATCH",
                    f"Operation {oid} ('{op.operation_name}') is assigned to machine "
                    f"{em.machine_id}, which does not list that process in its capabilities.",
                    machine_id=em.machine_id,
                    **refs,
                )
                continue
            active_eligible.append(em)
            used_machines.add(em.machine_id)
        if (
            op.eligible_machines
            and not active_eligible
            and all(
                machines.get(em.machine_id) is None or machines[em.machine_id].status != MachineStatus.ACTIVE
                for em in op.eligible_machines
            )
        ):
            rep.error(
                "NO_ACTIVE_ELIGIBLE_MACHINE",
                f"Operation {oid} has no active eligible machine. Activate a machine or select "
                "another eligible machine.",
                **refs,
            )

        for pred in op.predecessors:
            if pred not in {o.operation_id for o in data.operations}:
                rep.error(
                    "MISSING_PREDECESSOR",
                    f"Operation {oid} references predecessor '{pred}', which does not exist.",
                    **refs,
                )
            else:
                pred_op = next(o for o in data.operations if o.operation_id == pred)
                if pred_op.order_id != op.order_id:
                    rep.error(
                        "CROSS_ORDER_DEPENDENCY",
                        f"Operation {oid} depends on {pred} of order {pred_op.order_id}. "
                        "Cross-order dependencies are not supported.",
                        **refs,
                    )
                elif pred not in scheduled_by_id:
                    rep.error(
                        "PREDECESSOR_NOT_SCHEDULED",
                        f"Operation {oid} depends on {pred}, which is archived/not scheduled.",
                        **refs,
                    )

    # machines used by scheduled operations must have a calendar
    for mid in sorted(used_machines):
        if not effective_windows(machines[mid], horizon):
            rep.error(
                "NO_AVAILABILITY",
                f"Machine {mid} is used by scheduled operations but has no availability within "
                "the horizon. Unknown availability is never treated as unlimited - add windows.",
                machine_id=mid,
            )

    # ---- precedence cycles -----------------------------------------------------------------
    preds = {op.operation_id: [p for p in op.predecessors if p in scheduled_by_id] for op in scheduled_ops}
    cycle = find_cycle(preds.keys(), preds)
    if cycle:
        rep.error(
            "DEPENDENCY_CYCLE",
            "The operation dependency graph contains a cycle: " + " -> ".join(cycle) + ".",
            operation_id=cycle[0],
        )

    # ---- changeovers --------------------------------------------------------------------------
    if settings.changeover_enabled:
        _validate_changeovers(data, scheduled_ops, machines, rep)

    # ---- diagnostics (warnings only: the solver decides feasibility) ----------------------------
    _diagnostics(data, scheduled_ops, machines, orders, preds, rep)

    estimated = [op.operation_id for op in scheduled_ops if op.duration_is_estimate]
    if estimated:
        rep.warn(
            "ESTIMATED_DURATIONS",
            f"{len(estimated)} of {len(scheduled_ops)} scheduled operation(s) use estimated "
            "durations; the schedule depends on those estimates and is not a measured plan.",
        )
    if not settings.changeover_enabled:
        rep.warn(
            "CHANGEOVERS_UNMODELLED",
            "Changeovers are not modelled in this run: setup time between operations is not "
            "considered and is not optimized.",
        )
    return rep


def _validate_changeovers(data, scheduled_ops, machines, rep: ValidationReport) -> None:
    for op in scheduled_ops:
        if op.changeover_category is None:
            rep.error(
                "MISSING_CHANGEOVER_CATEGORY",
                f"Operation {op.operation_id} has no changeover category but changeovers are "
                "enabled. Set a category (unknown transitions are never treated as zero).",
                operation_id=op.operation_id,
                order_id=op.order_id,
            )
    matrix = {(r.from_category, r.to_category): r.minutes for r in data.changeover_rules}
    known = {c for pair in matrix for c in pair}
    used_categories = {op.changeover_category for op in scheduled_ops if op.changeover_category}
    for cat in sorted(used_categories - known):
        rep.error(
            "UNKNOWN_CHANGEOVER_CATEGORY",
            f"Changeover category '{cat}' is used by an operation but appears in no changeover rule.",
        )
    per_machine: dict[str, set[str]] = {}
    for op in scheduled_ops:
        if op.changeover_category is None:
            continue
        for em in op.eligible_machines:
            m = machines.get(em.machine_id)
            if m is not None and m.status == MachineStatus.ACTIVE:
                per_machine.setdefault(em.machine_id, set()).add(op.changeover_category)
    for mid, cats in sorted(per_machine.items()):
        ordered = sorted(cats)
        for a in ordered:
            for b in ordered:
                if (a, b) not in matrix:
                    rep.error(
                        "MISSING_TRANSITION",
                        f"Machine {mid}: no changeover duration defined for {a} -> {b}. Enter an "
                        "explicit value (0 is allowed) - missing transitions are never assumed zero.",
                        machine_id=mid,
                    )
        violation = _first_triangle_violation(ordered, matrix)
        if violation is not None:
            a, b, c = violation
            rep.error(
                "TRIANGLE_INEQUALITY",
                f"Machine {mid}: changeover {a}->{b} ({matrix[(a, b)]} min) is longer than "
                f"{a}->{c}->{b} ({matrix[(a, c)] + matrix[(c, b)]} min). This model requires "
                "transitions to satisfy the triangle inequality; revise the matrix.",
                machine_id=mid,
            )
    for rule_cat in sorted(known - used_categories):
        rep.warn(
            "UNUSED_CHANGEOVER_CATEGORY",
            f"Changeover category '{rule_cat}' is not used by any scheduled operation.",
        )


def _first_triangle_violation(categories: list[str], matrix: dict) -> tuple[str, str, str] | None:
    """First (a, b, c) with s(a,b) > s(a,c) + s(c,b), considering only defined entries."""
    for a in categories:
        for b in categories:
            for c in categories:
                if all(k in matrix for k in ((a, b), (a, c), (c, b))):
                    if matrix[(a, b)] > matrix[(a, c)] + matrix[(c, b)]:
                        return a, b, c
    return None


def _diagnostics(data, scheduled_ops, machines, orders, preds, rep: ValidationReport) -> None:
    horizon = data.settings.horizon_end
    min_duration: dict[str, int] = {}
    for op in scheduled_ops:
        options = []
        longest_window = 0
        for em in op.eligible_machines:
            m = machines.get(em.machine_id)
            if (
                m is None
                or m.status != MachineStatus.ACTIVE
                or op.operation_name not in m.supported_processes
            ):
                continue
            d = em.duration_override or op.processing_duration
            options.append(d)
            for w in effective_windows(m, horizon):
                longest_window = max(longest_window, w[1] - w[0])
        if not options:
            continue
        min_duration[op.operation_id] = min(options)
        if min(options) > longest_window:
            rep.warn(
                "OP_DOES_NOT_FIT",
                f"Operation {op.operation_id} (min duration {min(options)} min) does not fit in any "
                f"availability window of its eligible machines (longest window {longest_window} min). "
                "Operations are non-preemptive, so the solver will report this model as infeasible.",
                operation_id=op.operation_id,
                order_id=op.order_id,
            )
    # critical path versus release/horizon/hard due date (needs an acyclic graph)
    try:
        topo = topological_order(preds.keys(), preds)
    except ValueError:
        return
    earliest_end: dict[str, int] = {}
    by_id = {op.operation_id: op for op in scheduled_ops}
    for oid in topo:
        op = by_id[oid]
        order = orders[op.order_id]
        start = max([order.release_time] + [earliest_end[p] for p in preds[oid]])
        earliest_end[oid] = start + min_duration.get(oid, op.processing_duration)
    for order_id in sorted({op.order_id for op in scheduled_ops}):
        ends = [earliest_end[op.operation_id] for op in scheduled_ops if op.order_id == order_id]
        bound = max(ends)
        if bound > horizon:
            rep.warn(
                "ORDER_EXCEEDS_HORIZON",
                f"Order {order_id}: even with no machine contention its operations cannot finish "
                f"before minute {bound}, beyond the horizon end ({horizon}). The model will be "
                "infeasible for this horizon (a longer horizon might be feasible).",
                order_id=order_id,
            )
        if data.settings.enforce_due_dates and bound > orders[order_id].due_time:
            rep.warn(
                "HARD_DUE_UNREACHABLE",
                f"Order {order_id}: hard due dates are enforced but the order cannot finish before "
                f"minute {bound}, after its due time ({orders[order_id].due_time}).",
                order_id=order_id,
            )
