"""Immutable scheduling input snapshot, candidate schedules and planning-data container.

The *snapshot* contains exactly the scheduling-relevant data (technical_specification 5.6,
11.3, 11.4): it is what the solver models, what the independent validator checks and what
is stored with every run. Display-only fields (names, notes, descriptions, quantities) are
deliberately excluded so that editing them cannot mark a schedule stale.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .intervals import Interval, subtract
from .models import (
    ChangeoverRule,
    MachineRecord,
    MachineStatus,
    OperationRecord,
    OperationStatus,
    OrderRecord,
    OrderStatus,
    PlanningSettings,
)


@dataclass(frozen=True)
class OrderSpec:
    order_id: str
    release_time: int
    due_time: int
    weight: int | None = None


@dataclass(frozen=True)
class MachineSpec:
    machine_id: str
    windows: tuple[Interval, ...]  # effective availability (windows minus downtime), sorted


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    order_id: str
    predecessors: tuple[str, ...]
    options: tuple[tuple[str, int], ...]  # (machine_id, duration) - sorted by machine id
    changeover_category: str | None = None

    def duration_on(self, machine_id: str) -> int | None:
        for m, d in self.options:
            if m == machine_id:
                return d
        return None


@dataclass(frozen=True)
class ProblemSnapshot:
    horizon_end: int
    objective: str
    enforce_due_dates: bool
    changeover_enabled: bool
    origin_iso: str
    orders: tuple[OrderSpec, ...]
    machines: tuple[MachineSpec, ...]
    operations: tuple[OperationSpec, ...]
    setup: tuple[tuple[str, str, int], ...] = ()

    # ---- lookups -------------------------------------------------------------------
    def order_map(self) -> dict[str, OrderSpec]:
        return {o.order_id: o for o in self.orders}

    def machine_map(self) -> dict[str, MachineSpec]:
        return {m.machine_id: m for m in self.machines}

    def operation_map(self) -> dict[str, OperationSpec]:
        return {o.operation_id: o for o in self.operations}

    def setup_map(self) -> dict[tuple[str, str], int]:
        return {(a, b): m for a, b, m in self.setup}

    def operations_of(self, order_id: str) -> list[OperationSpec]:
        return [o for o in self.operations if o.order_id == order_id]

    def terminal_operations(self, order_id: str) -> list[OperationSpec]:
        """Operations of the order that are not a predecessor of another operation in it."""
        ops = self.operations_of(order_id)
        has_successor = {p for o in ops for p in o.predecessors}
        return [o for o in ops if o.operation_id not in has_successor]

    def setup_minutes(self, prev: OperationSpec, nxt: OperationSpec) -> int:
        """Changeover between consecutive operations (0 when changeovers are not modelled)."""
        if not self.changeover_enabled:
            return 0
        if prev.changeover_category is None or nxt.changeover_category is None:
            return 0
        return self.setup_map().get((prev.changeover_category, nxt.changeover_category), 0)

    # ---- serialisation / fingerprint ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "horizon_end": self.horizon_end,
            "objective": self.objective,
            "enforce_due_dates": self.enforce_due_dates,
            "changeover_enabled": self.changeover_enabled,
            "origin": self.origin_iso,
            "orders": [
                {"id": o.order_id, "release": o.release_time, "due": o.due_time, "weight": o.weight}
                for o in sorted(self.orders, key=lambda x: x.order_id)
            ],
            "machines": [
                {"id": m.machine_id, "windows": [list(w) for w in sorted(m.windows)]}
                for m in sorted(self.machines, key=lambda x: x.machine_id)
            ],
            "operations": [
                {
                    "id": o.operation_id,
                    "order": o.order_id,
                    "predecessors": sorted(o.predecessors),
                    "options": [[m, d] for m, d in sorted(o.options)],
                    "category": o.changeover_category if self.changeover_enabled else None,
                }
                for o in sorted(self.operations, key=lambda x: x.operation_id)
            ],
            "setup": [[a, b, m] for a, b, m in sorted(self.setup)] if self.changeover_enabled else [],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProblemSnapshot:
        return cls(
            horizon_end=data["horizon_end"],
            objective=data["objective"],
            enforce_due_dates=data["enforce_due_dates"],
            changeover_enabled=data["changeover_enabled"],
            origin_iso=data["origin"],
            orders=tuple(OrderSpec(o["id"], o["release"], o["due"], o.get("weight")) for o in data["orders"]),
            machines=tuple(
                MachineSpec(m["id"], tuple((w[0], w[1]) for w in m["windows"])) for m in data["machines"]
            ),
            operations=tuple(
                OperationSpec(
                    o["id"],
                    o["order"],
                    tuple(o["predecessors"]),
                    tuple((m, d) for m, d in o["options"]),
                    o.get("category"),
                )
                for o in data["operations"]
            ),
            setup=tuple((a, b, m) for a, b, m in data.get("setup", [])),
        )

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        """SHA-256 of the canonical scheduling-relevant representation.

        Independent of row order and of display-only fields (names, notes, quantities...).
        """
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScheduledOperation:
    """One scheduled operation. Deliberately has *no* value checks: the independent validator
    must be able to receive (and reject) corrupted candidates."""

    operation_id: str
    order_id: str
    machine_id: str
    start: int
    end: int
    duration: int


@dataclass
class CandidateSchedule:
    """A schedule as extracted from the solver (or a test), with the solver's own claims."""

    assignments: list[ScheduledOperation]
    claimed_completion: dict[str, int] = field(default_factory=dict)
    claimed_tardiness: dict[str, int] = field(default_factory=dict)
    claimed_makespan: int | None = None
    claimed_objective: int | None = None


@dataclass
class PlanningData:
    """Everything the planner has saved (all statuses), before filtering to a snapshot."""

    orders: list[OrderRecord]
    machines: list[MachineRecord]
    operations: list[OperationRecord]
    changeover_rules: list[ChangeoverRule]
    settings: PlanningSettings


def effective_windows(machine: MachineRecord, horizon_end: int) -> tuple[Interval, ...]:
    """Availability windows minus downtime, clipped to the planning horizon."""
    windows = [(i.start, min(i.end, horizon_end)) for i in machine.availability if i.start < horizon_end]
    blocked = [i.as_tuple() for i in machine.downtime]
    return tuple(subtract(windows, blocked))


def compile_snapshot(data: PlanningData) -> ProblemSnapshot:
    """Build the immutable snapshot from validated planning data.

    Only ``ready`` orders, their ``active`` operations and ``active`` machines are scheduled.
    Callers must run input validation first; this function does not re-validate references.
    """
    settings = data.settings
    orders = tuple(
        OrderSpec(o.order_id, o.release_time, o.due_time, o.weight)
        for o in sorted(data.orders, key=lambda x: x.order_id)
        if o.status == OrderStatus.READY
    )
    scheduled_orders = {o.order_id for o in orders}
    active_machines = {m.machine_id: m for m in data.machines if m.status == MachineStatus.ACTIVE}
    machines = tuple(
        MachineSpec(mid, effective_windows(m, settings.horizon_end))
        for mid, m in sorted(active_machines.items())
    )
    operations: list[OperationSpec] = []
    for op in sorted(data.operations, key=lambda x: x.operation_id):
        if op.status != OperationStatus.ACTIVE or op.order_id not in scheduled_orders:
            continue
        options = tuple(
            sorted(
                (em.machine_id, em.duration_override or op.processing_duration)
                for em in op.eligible_machines
                if em.machine_id in active_machines
            )
        )
        operations.append(
            OperationSpec(
                op.operation_id,
                op.order_id,
                tuple(sorted(op.predecessors)),
                options,
                op.changeover_category,
            )
        )
    setup = (
        tuple(sorted((r.from_category, r.to_category, r.minutes) for r in data.changeover_rules))
        if settings.changeover_enabled
        else ()
    )
    return ProblemSnapshot(
        horizon_end=settings.horizon_end,
        objective=settings.objective.value,
        enforce_due_dates=settings.enforce_due_dates,
        changeover_enabled=settings.changeover_enabled,
        origin_iso=settings.origin.isoformat(),
        orders=orders,
        machines=machines,
        operations=tuple(operations),
        setup=setup,
    )
