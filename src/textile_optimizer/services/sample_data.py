"""Clearly labelled SYNTHETIC sample data.

Every record is flagged ``is_synthetic`` and uses a ``SYN-`` identifier prefix. Machines,
durations, due times, weights and changeover minutes are artificial values chosen only to
exercise the software. They are NOT measurements, typical industry values or factory data.
"""

from __future__ import annotations

from datetime import datetime

from ..domain.models import (
    ChangeoverRule,
    EligibleMachine,
    IntervalRecord,
    MachineRecord,
    Objective,
    OperationRecord,
    OrderRecord,
    PlanningSettings,
)
from ..errors import IntegrityConflictError
from .planning_service import PlanningService

SAMPLE_LABEL = "SYNTHETIC SAMPLE DATA - artificial values for software demonstration only"
DAY = 1440
SHIFT = 720  # sample calendar: 12 h available from each day's 08:00 origin offset


def _day_windows(days: int) -> list[IntervalRecord]:
    return [IntervalRecord(start=d * DAY, end=d * DAY + SHIFT) for d in range(days)]


def sample_settings() -> PlanningSettings:
    return PlanningSettings(
        origin=datetime(2026, 1, 5, 8, 0),
        horizon_end=3 * DAY,
        objective=Objective.TOTAL_TARDINESS,
        changeover_enabled=True,
        time_limit_seconds=20.0,
        dataset_label=SAMPLE_LABEL,
    )


def sample_machines() -> list[MachineRecord]:
    note = "SYNTHETIC sample machine"

    def machine(mid: str, name: str, mtype: str, process: str, downtime=()):
        return MachineRecord(
            machine_id=mid,
            machine_name=name,
            machine_type=mtype,
            supported_processes=[process],
            availability=_day_windows(3),
            downtime=[IntervalRecord(start=a, end=b) for a, b in downtime],
            notes=note,
            is_synthetic=True,
        )

    return [
        machine("SYN-KNIT-01", "Synthetic knitting machine 1", "knitting", "knitting"),
        machine("SYN-KNIT-02", "Synthetic knitting machine 2", "knitting", "knitting", [(200, 320)]),
        machine("SYN-DYE-01", "Synthetic dyeing machine 1", "dyeing", "dyeing"),
        machine("SYN-DYE-02", "Synthetic dyeing machine 2", "dyeing", "dyeing"),
        machine("SYN-FIN-01", "Synthetic finishing line 1", "finishing", "finishing"),
    ]


# (order, due, release, weight/priority, knit, dye, dye category, finish) - minutes, all artificial
_ORDERS = [
    ("SYN-ORD-001", 520, 0, 5, 150, 240, "SYN-DARK", 90),
    ("SYN-ORD-002", 560, 0, 3, 180, 200, "SYN-LIGHT", 60),
    ("SYN-ORD-003", 760, 240, 2, 120, 260, "SYN-DARK", 75),
    ("SYN-ORD-004", 800, 0, 4, 210, 180, "SYN-LIGHT", 100),
    ("SYN-ORD-005", 1000, 480, 1, 90, 220, "SYN-LIGHT", 60),
]


def sample_orders_and_operations() -> tuple[list[OrderRecord], list[OperationRecord]]:
    orders: list[OrderRecord] = []
    ops: list[OperationRecord] = []
    for oid, due, release, prio, knit, dye, dye_cat, fin in _ORDERS:
        n = oid.split("-")[-1]
        orders.append(
            OrderRecord(
                order_id=oid,
                product_code=f"SYN-PRODUCT-{n}",
                description="SYNTHETIC sample order",
                quantity=100.0 * int(n),
                quantity_unit="kg",
                release_time=release,
                due_time=due,
                priority=prio,
                weight=prio,
                status="ready",
                notes="SYNTHETIC: artificial quantities and times",
                is_synthetic=True,
            )
        )
        k, d, f = f"SYN-OP-{n}-KNIT", f"SYN-OP-{n}-DYE", f"SYN-OP-{n}-FIN"
        src = "SYNTHETIC estimate"
        ops.append(
            OperationRecord(
                operation_id=k,
                order_id=oid,
                operation_name="knitting",
                sequence=1,
                processing_duration=knit,
                duration_source=src,
                changeover_category="SYN-KNIT",
                eligible_machines=[
                    EligibleMachine(machine_id="SYN-KNIT-01"),
                    EligibleMachine(machine_id="SYN-KNIT-02"),
                ],
                is_synthetic=True,
                notes="SYNTHETIC",
            )
        )
        ops.append(
            OperationRecord(
                operation_id=d,
                order_id=oid,
                operation_name="dyeing",
                sequence=2,
                processing_duration=dye,
                duration_source=src,
                changeover_category=dye_cat,
                eligible_machines=[
                    EligibleMachine(machine_id="SYN-DYE-01"),
                    # machine-specific duration: synthetic 20% slower machine
                    EligibleMachine(machine_id="SYN-DYE-02", duration_override=int(dye * 1.2)),
                ],
                predecessors=[k],
                is_synthetic=True,
                notes="SYNTHETIC",
            )
        )
        ops.append(
            OperationRecord(
                operation_id=f,
                order_id=oid,
                operation_name="finishing",
                sequence=3,
                processing_duration=fin,
                duration_source=src,
                changeover_category="SYN-FINISH",
                eligible_machines=[EligibleMachine(machine_id="SYN-FIN-01")],
                predecessors=[d],
                is_synthetic=True,
                notes="SYNTHETIC",
            )
        )
    return orders, ops


def sample_changeover_rules() -> list[ChangeoverRule]:
    pairs = [
        ("SYN-KNIT", "SYN-KNIT", 0),
        ("SYN-FINISH", "SYN-FINISH", 0),
        ("SYN-LIGHT", "SYN-LIGHT", 0),
        ("SYN-DARK", "SYN-DARK", 0),
        ("SYN-LIGHT", "SYN-DARK", 45),
        ("SYN-DARK", "SYN-LIGHT", 90),
    ]
    return [ChangeoverRule(from_category=a, to_category=b, minutes=m) for a, b, m in pairs]


def load_sample_data(service: PlanningService) -> None:
    """Load the synthetic dataset into an EMPTY database (never overwrites user data)."""
    counts = service.repo.counts()
    if counts["orders"] or counts["machines"] or counts["operations"]:
        raise IntegrityConflictError(
            "Sample data can only be loaded into an empty database so that your own records "
            "are never overwritten or mixed with synthetic records."
        )
    for machine in sample_machines():
        service.save_machine(machine, is_new=True)
    orders, ops = sample_orders_and_operations()
    for order in orders:
        service.save_order(order, is_new=True)
    for op in ops:
        service.save_operation(op, is_new=True)
    service.save_changeover_rules(sample_changeover_rules())
    service.save_settings(sample_settings())
