import pytest
from pydantic import ValidationError

from textile_optimizer.domain.models import (
    ChangeoverRule,
    EligibleMachine,
    IntervalRecord,
    MachineRecord,
    OperationRecord,
    OrderRecord,
    PlanningSettings,
)
from textile_optimizer.errors import InputValidationError
from textile_optimizer.services.planning_service import build_record


def order(**over):
    base = dict(
        order_id="O1", product_code="P", quantity=10, quantity_unit="kg", release_time=0, due_time=100
    )
    base.update(over)
    return OrderRecord(**base)


def op(**over):
    base = dict(operation_id="A", order_id="O1", operation_name="dyeing", processing_duration=30)
    base.update(over)
    return OperationRecord(**base)


def test_valid_records_are_created():
    assert order().status.value == "draft"
    assert op().processing_duration == 30
    m = MachineRecord(
        machine_id="M", machine_name="n", machine_type="t", supported_processes=[" dyeing ", "dyeing"]
    )
    assert m.supported_processes == ["dyeing"]


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(order_id=""),  # missing identifier
        dict(order_id="bad id!"),
        dict(quantity=-5),
        dict(quantity=0),
        dict(quantity=float("nan")),
        dict(quantity_unit="furlongs"),  # unsupported unit
        dict(release_time=-1),
        dict(due_time=-3),
        dict(release_time=50, due_time=10),  # due before release
        dict(priority=9),
        dict(weight=-2),
        dict(status="finished"),  # unsupported status
        dict(product_code="  "),
    ],
)
def test_invalid_orders_rejected(kwargs):
    with pytest.raises(ValidationError):
        order(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(processing_duration=0),
        dict(processing_duration=-10),
        dict(predecessors=["A"]),  # self reference
        dict(predecessors=["B", "B"]),  # duplicate
        dict(eligible_machines=[EligibleMachine(machine_id="M"), EligibleMachine(machine_id="M")]),
        dict(operation_name=""),
        dict(status="gone"),
    ],
)
def test_invalid_operations_rejected(kwargs):
    with pytest.raises(ValidationError):
        op(**kwargs)


def test_machine_specific_duration_and_default():
    o = op(
        eligible_machines=[
            EligibleMachine(machine_id="M1"),
            EligibleMachine(machine_id="M2", duration_override=45),
        ]
    )
    assert o.duration_on("M1") == 30
    assert o.duration_on("M2") == 45
    assert o.duration_on("M3") is None
    with pytest.raises(ValidationError):
        EligibleMachine(machine_id="M", duration_override=0)


def test_interval_and_machine_validation():
    with pytest.raises(ValidationError):
        IntervalRecord(start=10, end=10)
    with pytest.raises(ValidationError):
        IntervalRecord(start=-1, end=5)
    with pytest.raises(ValidationError):
        MachineRecord(machine_id="M", machine_name="n", machine_type="t", supported_processes=[])


def test_changeover_and_settings_validation():
    with pytest.raises(ValidationError):
        ChangeoverRule(from_category="a", to_category="b", minutes=-1)
    with pytest.raises(ValidationError):
        PlanningSettings(horizon_end=0)
    with pytest.raises(ValidationError):
        PlanningSettings(time_limit_seconds=0)
    with pytest.raises(ValidationError):
        PlanningSettings(workers=0)


def test_build_record_gives_actionable_messages():
    with pytest.raises(InputValidationError) as exc:
        build_record(
            OrderRecord,
            order_id="",
            product_code="P",
            quantity=-1,
            quantity_unit="kg",
            release_time=0,
            due_time=1,
        )
    text = " ".join(exc.value.messages)
    assert "Order ID is required" in text
    assert "Quantity must be a positive number" in text
