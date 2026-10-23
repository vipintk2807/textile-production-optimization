"""Independent schedule validator.

Deliberately shares *no* code with the CP-SAT model builder: it re-derives every rule from
the immutable input snapshot with simple loops (technical_specification 10, testing_requirements 9).
It never looks at the solver status. A candidate is accepted only when ``passed`` is true.

Checked rules (all implemented rules; nothing else is implied to be checked):
  VAL_MISSING_OP / VAL_DUPLICATE_OP / VAL_UNKNOWN_OP  operation completeness
  VAL_UNKNOWN_ORDER                                    order reference
  VAL_UNKNOWN_MACHINE / VAL_INELIGIBLE_MACHINE         machine reference and eligibility
  VAL_NON_INTEGER / VAL_INTERVAL / VAL_DURATION        interval sanity and duration
  VAL_HORIZON / VAL_RELEASE / VAL_PRECEDENCE           horizon, release time, finish-to-start
  VAL_OVERLAP / VAL_AVAILABILITY / VAL_CHANGEOVER      machine exclusivity, calendars, setups
  VAL_HARD_DUE                                         hard due dates when enforced
  VAL_COMPLETION / VAL_TARDINESS / VAL_MAKESPAN / VAL_OBJECTIVE   claimed metrics vs recomputed
"""

from __future__ import annotations

from collections import Counter, defaultdict

from ..domain.snapshot import CandidateSchedule, ProblemSnapshot
from .report import ValidationReport


def validate_schedule(snapshot: ProblemSnapshot, candidate: CandidateSchedule) -> ValidationReport:  # noqa: C901
    rep = ValidationReport()
    ops = snapshot.operation_map()
    machines = snapshot.machine_map()
    orders = snapshot.order_map()
    assignments = list(candidate.assignments)

    # ---- 1/2. completeness: every required operation exactly once ------------------------
    counts = Counter(a.operation_id for a in assignments)
    for op_id in sorted(ops):
        if counts.get(op_id, 0) == 0:
            rep.error(
                "VAL_MISSING_OP",
                f"Required operation {op_id} is missing from the schedule.",
                operation_id=op_id,
                order_id=ops[op_id].order_id,
            )
        elif counts[op_id] > 1:
            rep.error(
                "VAL_DUPLICATE_OP",
                f"Operation {op_id} appears {counts[op_id]} times; it must appear exactly once.",
                operation_id=op_id,
                order_id=ops[op_id].order_id,
            )
    for op_id in sorted(set(counts) - set(ops)):
        rep.error(
            "VAL_UNKNOWN_OP", f"Scheduled operation {op_id} is not part of the input.", operation_id=op_id
        )

    # ---- per-assignment checks ------------------------------------------------------------
    usable: list = []  # assignments whose basic shape is sound enough for pairwise checks
    for a in assignments:
        refs = {"operation_id": a.operation_id, "order_id": a.order_id, "machine_id": a.machine_id}
        spec = ops.get(a.operation_id)
        ints_ok = all(isinstance(v, int) and not isinstance(v, bool) for v in (a.start, a.end, a.duration))
        if not ints_ok:
            rep.error(
                "VAL_NON_INTEGER",
                f"Operation {a.operation_id}: start, end and duration must be whole minutes.",
                **refs,
            )
            continue
        if spec is not None and a.order_id not in orders:
            rep.error(
                "VAL_UNKNOWN_ORDER",
                f"Operation {a.operation_id} references unknown order '{a.order_id}'.",
                **refs,
            )
        elif spec is not None and spec.order_id != a.order_id:
            rep.error(
                "VAL_UNKNOWN_ORDER",
                f"Operation {a.operation_id} belongs to order {spec.order_id}, not {a.order_id}.",
                **refs,
            )
        if a.machine_id not in machines:
            rep.error(
                "VAL_UNKNOWN_MACHINE",
                f"Operation {a.operation_id} uses unknown machine '{a.machine_id}'.",
                **refs,
            )
        expected = spec.duration_on(a.machine_id) if spec else None
        if spec is not None and a.machine_id in machines and expected is None:
            rep.error(
                "VAL_INELIGIBLE_MACHINE",
                f"Machine {a.machine_id} is not eligible for operation {a.operation_id}.",
                **refs,
            )
        if a.end <= a.start:
            rep.error(
                "VAL_INTERVAL",
                f"Operation {a.operation_id}: end ({a.end}) must be after start ({a.start}).",
                interval=(a.start, a.end),
                **refs,
            )
            continue
        if a.end - a.start != a.duration:
            rep.error(
                "VAL_DURATION",
                f"Operation {a.operation_id}: end-start is {a.end - a.start} but the stated "
                f"duration is {a.duration}.",
                interval=(a.start, a.end),
                **refs,
            )
        if expected is not None and a.end - a.start != expected:
            rep.error(
                "VAL_DURATION",
                f"Operation {a.operation_id} on {a.machine_id}: scheduled length "
                f"{a.end - a.start} differs from the required duration {expected}.",
                interval=(a.start, a.end),
                **refs,
            )
        if a.start < 0 or a.end > snapshot.horizon_end:
            rep.error(
                "VAL_HORIZON",
                f"Operation {a.operation_id} [{a.start}, {a.end}) is outside the planning "
                f"horizon [0, {snapshot.horizon_end}].",
                interval=(a.start, a.end),
                **refs,
            )
        order = orders.get(spec.order_id) if spec else None
        if order is not None and a.start < order.release_time:
            rep.error(
                "VAL_RELEASE",
                f"Operation {a.operation_id} starts at {a.start}, before the release time "
                f"{order.release_time} of order {order.order_id}.",
                interval=(a.start, a.end),
                **refs,
            )
        machine = machines.get(a.machine_id)
        if machine is not None and not any(w[0] <= a.start and a.end <= w[1] for w in machine.windows):
            rep.error(
                "VAL_AVAILABILITY",
                f"Operation {a.operation_id} [{a.start}, {a.end}) is not fully inside an "
                f"availability window of machine {a.machine_id}.",
                interval=(a.start, a.end),
                **refs,
            )
        usable.append(a)

    # ---- precedence (finish-to-start) -------------------------------------------------------
    by_op: dict[str, list] = defaultdict(list)
    for a in usable:
        by_op[a.operation_id].append(a)
    for op_id, spec in sorted(ops.items()):
        for pred in spec.predecessors:
            for succ_a in by_op.get(op_id, []):
                for pred_a in by_op.get(pred, []):
                    if succ_a.start < pred_a.end:
                        rep.error(
                            "VAL_PRECEDENCE",
                            f"Operation {op_id} starts at {succ_a.start}, before its predecessor "
                            f"{pred} finishes at {pred_a.end}.",
                            operation_id=op_id,
                            order_id=spec.order_id,
                            interval=(succ_a.start, succ_a.end),
                        )

    # ---- machine exclusivity and changeovers -------------------------------------------------
    per_machine: dict[str, list] = defaultdict(list)
    for a in usable:
        per_machine[a.machine_id].append(a)
    for machine_id, items in sorted(per_machine.items()):
        items = sorted(items, key=lambda x: (x.start, x.end, x.operation_id))
        for i, first in enumerate(items):
            for second in items[i + 1 :]:
                if second.start >= first.end:
                    break
                rep.error(
                    "VAL_OVERLAP",
                    f"Operations {first.operation_id} [{first.start}, {first.end}) and "
                    f"{second.operation_id} [{second.start}, {second.end}) overlap on machine "
                    f"{machine_id}.",
                    machine_id=machine_id,
                    interval=(second.start, min(first.end, second.end)),
                )
        if snapshot.changeover_enabled:
            for prev, nxt in zip(items, items[1:], strict=False):
                p, n = ops.get(prev.operation_id), ops.get(nxt.operation_id)
                if p is None or n is None:
                    continue
                needed = snapshot.setup_minutes(p, n)
                gap = nxt.start - prev.end
                if gap < needed:
                    rep.error(
                        "VAL_CHANGEOVER",
                        f"Machine {machine_id}: {needed} min changeover required between "
                        f"{prev.operation_id} and {nxt.operation_id}, but the gap is {gap} min.",
                        machine_id=machine_id,
                        operation_id=nxt.operation_id,
                        interval=(prev.end, nxt.start),
                    )

    # ---- completion, tardiness, objective (recomputed here, independent of reporting.metrics) --
    end_of: dict[str, int] = {}
    for a in usable:
        end_of[a.operation_id] = max(a.end, end_of.get(a.operation_id, a.end))
    recomputed_tardiness: dict[str, int] = {}
    for order in snapshot.orders:
        terminals = snapshot.terminal_operations(order.order_id)
        if not terminals or any(t.operation_id not in end_of for t in terminals):
            continue
        completion = max(end_of[t.operation_id] for t in terminals)
        tardy = max(0, completion - order.due_time)
        recomputed_tardiness[order.order_id] = tardy
        claimed_c = candidate.claimed_completion.get(order.order_id)
        if claimed_c is not None and claimed_c != completion:
            rep.error(
                "VAL_COMPLETION",
                f"Order {order.order_id}: claimed completion {claimed_c} but the schedule "
                f"gives {completion}.",
                order_id=order.order_id,
            )
        claimed_t = candidate.claimed_tardiness.get(order.order_id)
        if claimed_t is not None and claimed_t != tardy:
            rep.error(
                "VAL_TARDINESS",
                f"Order {order.order_id}: claimed tardiness {claimed_t} but the schedule gives {tardy}.",
                order_id=order.order_id,
            )
        if snapshot.enforce_due_dates and tardy > 0:
            rep.error(
                "VAL_HARD_DUE",
                f"Order {order.order_id} completes at {completion}, after its due time "
                f"{order.due_time}, but due dates are enforced as hard constraints.",
                order_id=order.order_id,
            )

    if usable:
        makespan = max(a.end for a in usable)
        if candidate.claimed_makespan is not None and candidate.claimed_makespan != makespan:
            rep.error(
                "VAL_MAKESPAN",
                f"Claimed makespan {candidate.claimed_makespan} but the schedule gives {makespan}.",
            )
    else:
        makespan = None

    if candidate.claimed_objective is not None and rep.passed:
        if snapshot.objective == "makespan":
            recomputed = makespan
        elif snapshot.objective == "total_tardiness":
            recomputed = sum(recomputed_tardiness.values())
        else:
            weights = {o.order_id: o.weight for o in snapshot.orders}
            recomputed = (
                None
                if any(weights[o] is None for o in recomputed_tardiness)
                else sum(weights[o] * t for o, t in recomputed_tardiness.items())
            )
        if recomputed is None or round(candidate.claimed_objective) != recomputed:
            rep.error(
                "VAL_OBJECTIVE",
                f"Claimed objective value {candidate.claimed_objective} does not match the "
                f"recomputed value {recomputed} for objective '{snapshot.objective}'.",
            )

    if not snapshot.changeover_enabled:
        rep.warn(
            "CHANGEOVERS_UNMODELLED",
            "Changeovers are not modelled; the validator did not check any setup time.",
        )
    rep.warn(
        "MODEL_VALIDATION_ONLY",
        "Validation covers only the implemented model constraints. It does not establish "
        "operational feasibility on the factory floor.",
    )
    return rep
