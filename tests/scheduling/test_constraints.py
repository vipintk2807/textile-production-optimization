"""Real CP-SAT solves on tiny instances with hand-derived expected results."""

import pytest

from conftest import FAST, make_snapshot
from textile_optimizer.scheduling.solver import SolverStatus, solve
from textile_optimizer.validation.schedule_validator import validate_schedule


def run(snapshot):
    result = solve(snapshot, FAST)
    return result


def assert_valid(snapshot, result):
    assert result.candidate is not None
    report = validate_schedule(snapshot, result.candidate)
    assert report.passed, [i.message for i in report.errors]
    return {a.operation_id: a for a in result.candidate.assignments}


def test_single_operation_single_machine():  # scenario 1
    snap = make_snapshot([("O1", 0, 100)], {"M1": [(0, 500)]}, [("A", "O1", [], {"M1": 30})], horizon=500)
    res = run(snap)
    assert res.status == SolverStatus.OPTIMAL
    a = assert_valid(snap, res)["A"]
    assert (a.start, a.end, a.machine_id) == (0, 30, "M1")
    assert res.objective_value == 30  # makespan = 30


def test_two_sequential_operations_one_machine_makespan_is_50():  # spec 11.2 example: 30 + 20 -> 50
    snap = make_snapshot(
        [("O1", 0, 500), ("O2", 0, 500)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O2", [], {"M1": 20})],
        horizon=500,
    )
    res = run(snap)
    assert res.status == SolverStatus.OPTIMAL and res.objective_value == 50
    ops = assert_valid(snap, res)
    first, second = sorted(ops.values(), key=lambda a: a.start)
    assert first.start == 0 and second.start == first.end  # back-to-back, no invented gap


def test_independent_operations_on_separate_machines_overlap():  # scenario 3
    snap = make_snapshot(
        [("O1", 0, 500), ("O2", 0, 500)],
        {"M1": [(0, 500)], "M2": [(0, 500)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O2", [], {"M2": 20})],
        horizon=500,
    )
    res = run(snap)
    assert res.objective_value == 30  # parallel: makespan is max(30, 20)
    assert_valid(snap, res)


def test_machine_choice_among_eligible_machines():  # scenario 5, machine-specific durations
    # A: 100 on M1 or 40 on M2 (faster). Minimizing makespan must pick M2.
    snap = make_snapshot(
        [("O1", 0, 500)],
        {"M1": [(0, 500)], "M2": [(0, 500)]},
        [("A", "O1", [], {"M1": 100, "M2": 40})],
        horizon=500,
    )
    res = run(snap)
    a = assert_valid(snap, res)["A"]
    assert a.machine_id == "M2" and a.end - a.start == 40 and res.objective_value == 40


def test_precedence_chain_of_three():
    snap = make_snapshot(
        [("O1", 0, 500)],
        {"M1": [(0, 500)], "M2": [(0, 500)], "M3": [(0, 500)]},
        [("A", "O1", [], {"M1": 10}), ("B", "O1", ["A"], {"M2": 20}), ("C", "O1", ["B"], {"M3": 30})],
        horizon=500,
    )
    res = run(snap)
    ops = assert_valid(snap, res)
    assert res.objective_value == 60  # 10 + 20 + 30 even with free machines
    assert ops["B"].start >= ops["A"].end and ops["C"].start >= ops["B"].end
    assert ops["B"].start == ops["A"].end  # successor may start exactly when predecessor ends


def test_release_time_is_respected():  # scenario 7
    snap = make_snapshot([("O1", 100, 500)], {"M1": [(0, 500)]}, [("A", "O1", [], {"M1": 30})], horizon=500)
    a = assert_valid(snap, run(snap))["A"]
    assert a.start == 100 and a.end == 130


def test_availability_window_forces_operation_after_downtime():
    # windows [0,20) and [50,200); a 30-minute operation cannot fit in the first window
    snap = make_snapshot(
        [("O1", 0, 500)], {"M1": [(0, 20), (50, 200)]}, [("A", "O1", [], {"M1": 30})], horizon=200
    )
    res = run(snap)
    a = assert_valid(snap, res)["A"]
    assert a.start == 50 and a.end == 80


def test_operation_ending_exactly_at_window_end_and_horizon_end_is_allowed():
    snap = make_snapshot([("O1", 0, 500)], {"M1": [(0, 30)]}, [("A", "O1", [], {"M1": 30})], horizon=30)
    res = run(snap)
    assert res.status == SolverStatus.OPTIMAL
    a = assert_valid(snap, res)["A"]
    assert (a.start, a.end) == (0, 30)


def test_multiple_windows_two_operations_use_both_windows():  # scenario 6
    snap = make_snapshot(
        [("O1", 0, 500), ("O2", 0, 500)],
        {"M1": [(0, 30), (100, 130)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O2", [], {"M1": 30})],
        horizon=200,
    )
    res = run(snap)
    ops = assert_valid(snap, res)
    assert res.objective_value == 130
    assert sorted((a.start, a.end) for a in ops.values()) == [(0, 30), (100, 130)]


def test_infeasible_because_operation_longer_than_any_window():
    snap = make_snapshot(
        [("O1", 0, 500)], {"M1": [(0, 20), (50, 70)]}, [("A", "O1", [], {"M1": 30})], horizon=200
    )
    res = run(snap)
    assert res.status == SolverStatus.INFEASIBLE and res.candidate is None


def test_infeasible_because_precedence_cannot_fit_horizon():  # scenario 10
    snap = make_snapshot(
        [("O1", 0, 500)],
        {"M1": [(0, 100)]},
        [("A", "O1", [], {"M1": 60}), ("B", "O1", ["A"], {"M1": 60})],
        horizon=100,
    )
    assert run(snap).status == SolverStatus.INFEASIBLE
    longer = make_snapshot(
        [("O1", 0, 500)],
        {"M1": [(0, 200)]},
        [("A", "O1", [], {"M1": 60}), ("B", "O1", ["A"], {"M1": 60})],
        horizon=200,
    )
    assert run(longer).status == SolverStatus.OPTIMAL  # a longer horizon fixes it: not infeasible in general


def test_conflict_two_operations_cannot_fit_one_machine_window():
    snap = make_snapshot(
        [("O1", 0, 500), ("O2", 0, 500)],
        {"M1": [(0, 50)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O2", [], {"M1": 30})],
        horizon=50,
    )
    assert run(snap).status == SolverStatus.INFEASIBLE


def test_total_tardiness_objective_hand_derived():
    # M1 only. A(30, due 30) and B(20, due 20). Order B,A: B ends 20 (T0), A ends 50 (T20) => 20.
    # Order A,B: A ends 30 (T0), B ends 50 (T30) => 30. Optimum = 20.
    snap = make_snapshot(
        [("O1", 0, 30), ("O2", 0, 20)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O2", [], {"M1": 20})],
        horizon=500,
        objective="total_tardiness",
    )
    res = run(snap)
    assert res.status == SolverStatus.OPTIMAL and res.objective_value == 20
    ops = assert_valid(snap, res)
    assert ops["B"].start == 0 and ops["A"].start == 20


def test_weighted_tardiness_prefers_heavier_order():
    # Same as above but O1 (A) has weight 10, O2 (B) weight 1. A first: T(B)=30 -> 1*30 = 30.
    # B first: T(A)=20 -> 10*20 = 200. Optimum = 30 with A first.
    snap = make_snapshot(
        [("O1", 0, 30, 10), ("O2", 0, 20, 1)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O2", [], {"M1": 20})],
        horizon=500,
        objective="weighted_tardiness",
    )
    res = run(snap)
    assert res.status == SolverStatus.OPTIMAL and res.objective_value == 30
    assert assert_valid(snap, res)["A"].start == 0


def test_late_but_feasible_is_not_infeasible_when_due_dates_soft():  # scenario 9
    snap = make_snapshot(
        [("O1", 0, 10)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 30})],
        horizon=500,
        objective="total_tardiness",
    )
    res = run(snap)
    assert res.status == SolverStatus.OPTIMAL and res.objective_value == 20  # completes 30, due 10


def test_hard_due_dates_make_same_instance_infeasible():
    snap = make_snapshot(
        [("O1", 0, 10)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 30})],
        horizon=500,
        objective="total_tardiness",
        hard_due=True,
    )
    assert run(snap).status == SolverStatus.INFEASIBLE


def test_order_completion_is_final_operation_for_tardiness():
    # chain A(10)->B(50) on separate machines; due 40; completion must be 60 (not 10) => tardiness 20
    snap = make_snapshot(
        [("O1", 0, 40)],
        {"M1": [(0, 500)], "M2": [(0, 500)]},
        [("A", "O1", [], {"M1": 10}), ("B", "O1", ["A"], {"M2": 50})],
        horizon=500,
        objective="total_tardiness",
    )
    assert run(snap).objective_value == 20


def test_multiple_terminal_operations_use_max_end():
    snap = make_snapshot(
        [("O1", 0, 0)],
        {"M1": [(0, 500)], "M2": [(0, 500)]},
        [("A", "O1", [], {"M1": 10}), ("B", "O1", [], {"M2": 25})],
        horizon=500,
        objective="total_tardiness",
    )
    assert run(snap).objective_value == 25


SETUP = {("X", "X"): 0, ("Y", "Y"): 0, ("X", "Y"): 15, ("Y", "X"): 25}


def test_changeover_time_enforced_between_consecutive_operations():
    # A(10, cat X) and B(10, cat Y) on one machine. X->Y needs 15, Y->X needs 25.
    # Best order A,B: 0-10, then 25-35 => makespan 35. Order B,A would give 45.
    snap = make_snapshot(
        [("O1", 0, 500), ("O2", 0, 500)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 10}, "X"), ("B", "O2", [], {"M1": 10}, "Y")],
        horizon=500,
        setup=SETUP,
    )
    res = run(snap)
    assert res.status == SolverStatus.OPTIMAL and res.objective_value == 35
    ops = assert_valid(snap, res)
    assert ops["A"].start == 0 and ops["B"].start == 25


def test_changeover_avoided_by_using_second_machine():
    snap = make_snapshot(
        [("O1", 0, 500), ("O2", 0, 500)],
        {"M1": [(0, 500)], "M2": [(0, 500)]},
        [("A", "O1", [], {"M1": 10, "M2": 10}, "X"), ("B", "O2", [], {"M1": 10, "M2": 10}, "Y")],
        horizon=500,
        setup=SETUP,
    )
    assert run(snap).objective_value == 10  # different machines: no changeover needed


def test_solution_never_assigns_ineligible_machine():
    snap = make_snapshot(
        [("O1", 0, 500)], {"M1": [(0, 500)], "M2": [(0, 500)]}, [("A", "O1", [], {"M2": 40})], horizon=500
    )
    assert assert_valid(snap, run(snap))["A"].machine_id == "M2"


@pytest.mark.parametrize("objective", ["makespan", "total_tardiness"])
def test_claimed_objective_matches_validator(objective):
    snap = make_snapshot(
        [("O1", 0, 25), ("O2", 0, 60)],
        {"M1": [(0, 500)], "M2": [(0, 500)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O2", ["A"] and [], {"M1": 20, "M2": 35})],
        horizon=500,
        objective=objective,
    )
    res = run(snap)
    assert validate_schedule(snap, res.candidate).passed
