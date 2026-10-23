"""VAL-01 .. VAL-17 from testing_requirements 9.2. Candidates are hand-built, never solver output."""

from dataclasses import replace

import pytest

from conftest import cand, make_snapshot, sched
from textile_optimizer.validation.schedule_validator import validate_schedule

# O1: A(M1, 30) -> B(M2, 20), release 10, due 200.  O2: C(M1, 20), due 40.
SNAP = make_snapshot(
    [("O1", 10, 200), ("O2", 0, 40)],
    {"M1": [(0, 100), (150, 300)], "M2": [(0, 300)], "M3": [(0, 300)]},
    [
        ("A", "O1", [], {"M1": 30}),
        ("B", "O1", ["A"], {"M2": 20}),
        ("C", "O2", [], {"M1": 20}),
    ],
    horizon=300,
)
GOOD = [sched("A", "O1", "M1", 10, 40), sched("B", "O1", "M2", 40, 60), sched("C", "O2", "M1", 40, 60)]


def check(assignments, snapshot=SNAP, **claims):
    return validate_schedule(snapshot, cand(*assignments, **claims))


def failing_codes(report):
    return report.error_codes()


def test_baseline_good_schedule_passes():
    rep = check(
        GOOD,
        claimed_completion={"O1": 60, "O2": 60},
        claimed_tardiness={"O1": 0, "O2": 20},
        claimed_makespan=60,
    )
    assert rep.passed, [i.message for i in rep.errors]


def test_val_01_missing_operation():
    assert "VAL_MISSING_OP" in failing_codes(check(GOOD[:2]))


def test_val_02_duplicate_operation():
    assert "VAL_DUPLICATE_OP" in failing_codes(check([*GOOD, sched("A", "O1", "M1", 60, 90)]))


def test_val_03_unknown_order_reference():
    bad = [replace(GOOD[0], order_id="NOPE"), *GOOD[1:]]
    assert "VAL_UNKNOWN_ORDER" in failing_codes(check(bad))


def test_val_04_unknown_machine_reference():
    bad = [replace(GOOD[0], machine_id="GHOST"), *GOOD[1:]]
    assert "VAL_UNKNOWN_MACHINE" in failing_codes(check(bad))


def test_val_05_ineligible_machine_assigned():
    bad = [sched("A", "O1", "M3", 10, 40), *GOOD[1:]]  # M3 exists but is not eligible for A
    assert "VAL_INELIGIBLE_MACHINE" in failing_codes(check(bad))


def test_val_06_incorrect_duration():
    bad = [sched("A", "O1", "M1", 10, 35), *GOOD[1:]]  # 25 instead of 30
    assert "VAL_DURATION" in failing_codes(check(bad))
    inconsistent = [sched("A", "O1", "M1", 10, 40, duration=99), *GOOD[1:]]  # stated duration lies
    assert "VAL_DURATION" in failing_codes(check(inconsistent))


@pytest.mark.parametrize("start,end", [(40, 40), (50, 40)])
def test_val_07_end_not_after_start(start, end):
    bad = [sched("A", "O1", "M1", 10, 40), sched("B", "O1", "M2", start, end, duration=20), GOOD[2]]
    assert "VAL_INTERVAL" in failing_codes(check(bad))


def test_val_08_starts_before_release_time():
    bad = [
        sched("A", "O1", "M1", 0, 30),
        sched("B", "O1", "M2", 30, 50),
        GOOD[2].__class__("C", "O2", "M1", 30, 50, 20),
    ]
    rep = check(bad)
    assert "VAL_RELEASE" in failing_codes(rep)  # O1 releases at 10


def test_val_09_successor_before_predecessor_finishes():
    bad = [GOOD[0], sched("B", "O1", "M2", 39, 59), GOOD[2]]
    assert "VAL_PRECEDENCE" in failing_codes(check(bad))


def test_val_10_overlap_on_one_machine():
    bad = [GOOD[0], GOOD[1], sched("C", "O2", "M1", 30, 50)]  # overlaps A (10-40) on M1
    assert "VAL_OVERLAP" in failing_codes(check(bad))


def test_val_11_outside_availability_window():
    # M1 is unavailable in [100, 150): C at 90-110 crosses the gap
    bad = [GOOD[0], GOOD[1], sched("C", "O2", "M1", 90, 110)]
    assert "VAL_AVAILABILITY" in failing_codes(check(bad))


def test_val_12_beyond_planning_horizon():
    bad = [GOOD[0], GOOD[1], sched("C", "O2", "M1", 290, 310)]
    assert "VAL_HORIZON" in failing_codes(check(bad))


def test_val_13_incorrect_claimed_completion_time():
    rep = check(GOOD, claimed_completion={"O1": 40, "O2": 60})  # O1 really completes at 60, not 40
    assert "VAL_COMPLETION" in failing_codes(rep)


def test_val_14_incorrect_claimed_tardiness():
    rep = check(GOOD, claimed_tardiness={"O1": 0, "O2": 0})  # O2 completes 60, due 40: tardiness is 20
    assert "VAL_TARDINESS" in failing_codes(rep)


def test_val_15_changeover_violation():
    snap = make_snapshot(
        [("O1", 0, 500)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 10}, "X"), ("B", "O1", [], {"M1": 10}, "Y")],
        horizon=500,
        setup={("X", "X"): 0, ("Y", "Y"): 0, ("X", "Y"): 15, ("Y", "X"): 25},
    )
    short = [sched("A", "O1", "M1", 0, 10), sched("B", "O1", "M1", 20, 30)]  # gap 10 < 15
    assert "VAL_CHANGEOVER" in failing_codes(check(short, snap))
    ok = [sched("A", "O1", "M1", 0, 10), sched("B", "O1", "M1", 25, 35)]
    assert check(ok, snap).passed


def test_val_16_valid_schedule_with_late_order_soft_due_dates_passes():
    rep = check(GOOD, claimed_tardiness={"O1": 0, "O2": 20})
    assert rep.passed  # O2 is 20 minutes late but due dates are soft targets


def test_val_17_adjacent_half_open_intervals_pass():
    # A ends at 40 on M1 exactly when C starts on M1; B starts exactly when A ends
    assert check(GOOD).passed


def test_hard_due_dates_flag_late_orders_as_violations():
    snap = make_snapshot(
        [("O1", 10, 200), ("O2", 0, 40)],
        {"M1": [(0, 300)], "M2": [(0, 300)]},
        [("A", "O1", [], {"M1": 30}), ("B", "O1", ["A"], {"M2": 20}), ("C", "O2", [], {"M1": 20})],
        horizon=300,
        hard_due=True,
    )
    assert "VAL_HARD_DUE" in failing_codes(check(GOOD, snap))


def test_objective_claim_is_cross_checked():
    snap = make_snapshot(
        [("O1", 0, 10)],
        {"M1": [(0, 100)]},
        [("A", "O1", [], {"M1": 30})],
        horizon=100,
        objective="total_tardiness",
    )
    good = [sched("A", "O1", "M1", 0, 30)]
    assert check(good, snap, claimed_objective=20).passed
    assert "VAL_OBJECTIVE" in failing_codes(check(good, snap, claimed_objective=5))


def test_validator_never_trusts_solver_status_and_reports_identifiers():
    rep = check([GOOD[0], GOOD[1], sched("C", "O2", "M1", 30, 50)])
    issue = next(i for i in rep.errors if i.code == "VAL_OVERLAP")
    assert issue.machine_id == "M1" and issue.interval is not None and "overlap" in issue.message


def test_non_integer_values_rejected():
    bad = [replace(GOOD[0], start=10.5), *GOOD[1:]]
    assert "VAL_NON_INTEGER" in failing_codes(check(bad))
