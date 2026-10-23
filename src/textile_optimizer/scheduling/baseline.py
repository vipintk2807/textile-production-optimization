"""Simple, documented baseline scheduler used for comparison (project_explanation 11.3).

Method: *earliest-due-date list scheduling with earliest-finish machine selection*.

1. Repeatedly pick, among operations whose predecessors are all scheduled, the one whose order
   has the earliest due time (ties: order id, then operation id).
2. For each eligible machine compute the earliest start that respects the order release time,
   predecessor completion, the machine's previous operation plus any changeover, and lies fully
   inside one availability window; choose the machine with the earliest finish (ties: machine id).
3. Operations are appended to the end of a machine's sequence (no gap insertion).

It uses the same mandatory constraints as the optimizer. It is deterministic, not an optimizer,
and may fail to produce a schedule (e.g. horizon too short); in that case the failure is reported
and no schedule is invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.snapshot import CandidateSchedule, ProblemSnapshot, ScheduledOperation
from ..validation.schedule_validator import validate_schedule

BASELINE_METHOD = "EDD list scheduling with earliest-finish machine selection (append-only)"


@dataclass
class BaselineResult:
    candidate: CandidateSchedule | None
    valid: bool
    message: str
    method: str = BASELINE_METHOD


def _earliest_start(windows, earliest: int, duration: int) -> int | None:
    for w_start, w_end in windows:
        start = max(w_start, earliest)
        if start + duration <= w_end:
            return start
    return None


def run_baseline(snapshot: ProblemSnapshot) -> BaselineResult:
    orders = snapshot.order_map()
    machines = snapshot.machine_map()
    ops = snapshot.operation_map()
    scheduled: dict[str, ScheduledOperation] = {}
    machine_last: dict[str, ScheduledOperation] = {}

    remaining = set(ops)
    while remaining:
        ready = [ops[o] for o in remaining if all(p in scheduled for p in ops[o].predecessors)]
        if not ready:
            return BaselineResult(None, False, "Baseline could not continue: dependency cycle.")
        ready.sort(key=lambda o: (orders[o.order_id].due_time, o.order_id, o.operation_id))
        op = ready[0]
        order = orders[op.order_id]
        base_ready = max([order.release_time] + [scheduled[p].end for p in op.predecessors])
        best: tuple[int, str, int, int] | None = None  # (end, machine, start, duration)
        for machine_id, duration in op.options:
            machine = machines.get(machine_id)
            if machine is None:
                continue
            earliest = base_ready
            last = machine_last.get(machine_id)
            if last is not None:
                earliest = max(earliest, last.end + snapshot.setup_minutes(ops[last.operation_id], op))
            start = _earliest_start(machine.windows, earliest, duration)
            if start is None or start + duration > snapshot.horizon_end:
                continue
            candidate_key = (start + duration, machine_id, start, duration)
            if best is None or candidate_key < best:
                best = candidate_key
        if best is None:
            return BaselineResult(
                None,
                False,
                f"Baseline could not place operation {op.operation_id} on any eligible machine "
                "within availability and the horizon.",
            )
        end, machine_id, start, duration = best
        item = ScheduledOperation(op.operation_id, op.order_id, machine_id, start, end, duration)
        scheduled[op.operation_id] = item
        machine_last[machine_id] = item
        remaining.discard(op.operation_id)

    candidate = CandidateSchedule(assignments=[scheduled[o] for o in sorted(scheduled)])
    report = validate_schedule(snapshot, candidate)
    if not report.passed:
        return BaselineResult(
            candidate,
            False,
            "Baseline schedule failed validation: " + "; ".join(i.message for i in report.errors),
        )
    return BaselineResult(candidate, True, "Baseline schedule passed independent validation.")
