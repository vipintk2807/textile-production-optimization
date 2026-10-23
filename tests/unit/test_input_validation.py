"""Pre-solver validation: every blocking rule from the specification has a negative test."""

from helpers import data, machine, op, order
from textile_optimizer.domain.models import ChangeoverRule
from textile_optimizer.validation.input_validation import validate_inputs


def codes(report):
    return report.error_codes()


def test_valid_data_passes():
    rep = validate_inputs(data())
    assert rep.passed, [i.message for i in rep.errors]
    assert "CHANGEOVERS_UNMODELLED" in rep.codes()  # disclosed, not silently ignored


def test_operation_without_eligible_machine():  # scenario 11
    rep = validate_inputs(data(ops=[op(machines=())]))
    assert "NO_ELIGIBLE_MACHINE" in codes(rep)
    assert "OP-" not in rep.errors[0].message  # message names the real operation id
    assert "Operation A" in rep.errors[0].message


def test_unknown_machine_and_capability_mismatch():
    assert "UNKNOWN_MACHINE" in codes(validate_inputs(data(ops=[op(machines=("NOPE",))])))
    assert "CAPABILITY_MISMATCH" in codes(validate_inputs(data(ops=[op(name="knitting")])))


def test_missing_predecessor_cycle_and_cross_order():
    assert "MISSING_PREDECESSOR" in codes(validate_inputs(data(ops=[op(preds=("ZZ",))])))
    cyc = validate_inputs(data(ops=[op("A", preds=("B",)), op("B", preds=("A",))]))
    assert "DEPENDENCY_CYCLE" in codes(cyc)
    cross = validate_inputs(
        data(orders=[order("O1"), order("O2")], ops=[op("A", "O1"), op("B", "O2", preds=("A",))])
    )
    assert "CROSS_ORDER_DEPENDENCY" in codes(cross)


def test_ready_order_without_operations_and_no_orders():
    assert "ORDER_NO_OPERATIONS" in codes(validate_inputs(data(ops=[])))
    assert "NO_ORDERS" in codes(validate_inputs(data(orders=[order(status="draft")], ops=[])))


def test_draft_and_archived_orders_excluded_with_warning():
    rep = validate_inputs(data(orders=[order(), order("O2", status="draft")], ops=[op()]))
    assert rep.passed and "DRAFT_EXCLUDED" in rep.codes()


def test_release_outside_horizon():
    assert "RELEASE_OUTSIDE_HORIZON" in codes(
        validate_inputs(data(orders=[order(release_time=1000, due_time=1200)]))
    )


def test_calendar_rules_overlap_and_missing_availability():
    overlap = validate_inputs(data(machines=[machine(windows=((0, 100), (50, 200)))]))
    assert "AVAIL_OVERLAP" in codes(overlap)
    down = validate_inputs(data(machines=[machine(downtime=((10, 50), (40, 60)))]))
    assert "DOWNTIME_OVERLAP" in codes(down)
    none = validate_inputs(data(machines=[machine(windows=())]))
    assert "NO_AVAILABILITY" in codes(none)  # unknown availability is never unlimited


def test_window_beyond_horizon_is_clipped_with_warning():
    rep = validate_inputs(data(machines=[machine(windows=((0, 5000),))]))
    assert rep.passed and "AVAIL_CLIPPED" in rep.codes()


def test_inactive_machine_not_used():
    only_inactive = validate_inputs(data(machines=[machine(status="inactive")]))
    assert "NO_ACTIVE_ELIGIBLE_MACHINE" in codes(only_inactive)


def test_weighted_objective_requires_weights():
    rep = validate_inputs(data(objective="weighted_tardiness"))
    assert "MISSING_WEIGHT" in codes(rep)
    ok = validate_inputs(data(orders=[order(weight=2)], objective="weighted_tardiness"))
    assert ok.passed


def test_duplicate_ids_reported():
    rep = validate_inputs(data(orders=[order(), order()], ops=[op(), op()], machines=[machine(), machine()]))
    assert {"DUP_ORDER", "DUP_OPERATION", "DUP_MACHINE"} <= codes(rep)


def test_does_not_fit_diagnostic_is_a_warning_not_a_blocker():
    rep = validate_inputs(data(machines=[machine(windows=((0, 20),))], ops=[op(duration=30)]))
    assert rep.passed and "OP_DOES_NOT_FIT" in rep.codes()


def test_critical_path_beyond_horizon_warns():
    rep = validate_inputs(
        data(ops=[op("A", duration=600), op("B", preds=("A",), duration=600)], horizon_end=1000)
    )
    assert rep.passed and "ORDER_EXCEEDS_HORIZON" in rep.codes()


def _co(**kw):
    ops = [
        op("A", changeover_category="X"),
        op("B", changeover_category="Y"),
    ]
    return data(ops=ops, changeover_enabled=True, **kw)


def test_changeover_missing_transition_category_and_triangle():
    full = [
        ChangeoverRule(from_category=a, to_category=b, minutes=m)
        for a, b, m in [("X", "X", 0), ("Y", "Y", 0), ("X", "Y", 10), ("Y", "X", 10)]
    ]
    ok = _co()
    ok.changeover_rules = full
    assert validate_inputs(ok).passed
    missing = _co()
    missing.changeover_rules = full[:-1]
    assert "MISSING_TRANSITION" in codes(validate_inputs(missing))
    no_cat = data(ops=[op("A")], changeover_enabled=True)
    assert "MISSING_CHANGEOVER_CATEGORY" in codes(validate_inputs(no_cat))
    # A triangle violation needs a third category: X->Y is longer than X->Z->Y
    tri = data(
        ops=[
            op("A", changeover_category="X"),
            op("B", changeover_category="Y"),
            op("C", changeover_category="Z"),
        ],
        changeover_enabled=True,
    )
    cats = ["X", "Y", "Z"]
    vals = {(a, b): 0 if a == b else 10 for a in cats for b in cats}
    vals[("X", "Y")] = 50  # 50 > X->Z (10) + Z->Y (10)
    tri.changeover_rules = [
        ChangeoverRule(from_category=a, to_category=b, minutes=m) for (a, b), m in vals.items()
    ]
    assert "TRIANGLE_INEQUALITY" in codes(validate_inputs(tri))
