"""Record builders shared by tests (SYNTHETIC fixture data only)."""

from textile_optimizer.domain.models import (
    EligibleMachine,
    IntervalRecord,
    MachineRecord,
    OperationRecord,
    OrderRecord,
    PlanningSettings,
)
from textile_optimizer.domain.snapshot import PlanningData


def machine(mid="M1", process="dyeing", windows=((0, 1000),), downtime=(), status="active"):
    return MachineRecord(
        machine_id=mid,
        machine_name=mid,
        machine_type="t",
        supported_processes=[process],
        status=status,
        availability=[IntervalRecord(start=a, end=b) for a, b in windows],
        downtime=[IntervalRecord(start=a, end=b) for a, b in downtime],
    )


def order(oid="O1", status="ready", **kw):
    base = dict(
        order_id=oid,
        product_code="P",
        quantity=1,
        quantity_unit="kg",
        release_time=0,
        due_time=500,
        status=status,
    )
    base.update(kw)
    return OrderRecord(**base)


def op(oid="A", order_id="O1", machines=("M1",), preds=(), name="dyeing", duration=30, **kw):
    return OperationRecord(
        operation_id=oid,
        order_id=order_id,
        operation_name=name,
        processing_duration=duration,
        eligible_machines=[EligibleMachine(machine_id=m) for m in machines],
        predecessors=list(preds),
        **kw,
    )


def data(orders=None, machines=None, ops=None, rules=(), **settings):
    return PlanningData(
        orders=orders if orders is not None else [order()],
        machines=machines if machines is not None else [machine()],
        operations=ops if ops is not None else [op()],
        changeover_rules=list(rules),
        settings=PlanningSettings(horizon_end=settings.pop("horizon_end", 1000), **settings),
    )
