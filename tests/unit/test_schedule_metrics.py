"""Metrics verified against values derived by hand (not by the implementation)."""

from conftest import make_snapshot, sched
from textile_optimizer.reporting import metrics as mt

# Order O1: ops A(0-30) -> B(30-50) on M1; due 40  => completion 50, lateness +10, tardiness 10
# Order O2: op C(0-20) on M2; due 20  => completion 20, lateness 0, tardiness 0 (exactly on time)
# Order O3: op D(20-30) on M2; due 100 => completion 30, lateness -70, tardiness 0 (early)
SNAP = make_snapshot(
    [("O1", 0, 40, 3), ("O2", 0, 20, 1), ("O3", 0, 100, 2)],
    {"M1": [(0, 200)], "M2": [(0, 100), (150, 200)], "M3": []},
    [
        ("A", "O1", [], {"M1": 30}),
        ("B", "O1", ["A"], {"M1": 20}),
        ("C", "O2", [], {"M2": 20}),
        ("D", "O3", [], {"M2": 10}),
    ],
    horizon=200,
    objective="total_tardiness",
)
ASSIGN = [
    sched("A", "O1", "M1", 0, 30),
    sched("B", "O1", "M1", 30, 50),
    sched("C", "O2", "M2", 0, 20),
    sched("D", "O3", "M2", 20, 30),
]


def test_completion_uses_final_operation_not_intermediate():
    assert mt.completion_times(SNAP, ASSIGN) == {"O1": 50, "O2": 20, "O3": 30}


def test_lateness_and_tardiness_early_exact_late():
    comp = mt.completion_times(SNAP, ASSIGN)
    assert mt.lateness(SNAP, comp) == {"O1": 10, "O2": 0, "O3": -70}
    assert mt.tardiness(SNAP, comp) == {"O1": 10, "O2": 0, "O3": 0}


def test_total_weighted_tardiness_and_makespan():
    comp = mt.completion_times(SNAP, ASSIGN)
    tardy = mt.tardiness(SNAP, comp)
    assert mt.total_tardiness(tardy) == 10
    assert mt.weighted_tardiness(SNAP, tardy) == 3 * 10  # weight 3 * tardiness 10
    assert mt.makespan(ASSIGN) == 50
    assert mt.objective_value(SNAP, ASSIGN) == 10


def test_weighted_tardiness_unavailable_without_weights():
    snap = make_snapshot([("O1", 0, 10)], {"M1": [(0, 100)]}, [("A", "O1", [], {"M1": 30})])
    comp = mt.completion_times(snap, [sched("A", "O1", "M1", 0, 30)])
    assert mt.weighted_tardiness(snap, mt.tardiness(snap, comp)) is None


def test_no_completion_invented_for_partially_scheduled_order():
    partial = [sched("A", "O1", "M1", 0, 30)]  # B (terminal) missing
    assert "O1" not in mt.completion_times(SNAP, partial)


def test_utilization_numerator_denominator_and_unavailable():
    util = {u.machine_id: u for u in mt.machine_utilization(SNAP, ASSIGN)}
    # M1: processing 30+20 = 50 over available 200 -> 25.0 %
    assert util["M1"].processing_minutes == 50 and util["M1"].available_minutes == 200
    assert util["M1"].utilization_pct == 25.0
    # M2: processing 20+10 = 30 over available 100 + 50 = 150 -> 20.0 %
    assert util["M2"].available_minutes == 150 and util["M2"].utilization_pct == 20.0
    # M3: no windows -> utilization undefined, never 0 % and never a division error
    assert util["M3"].available_minutes == 0 and util["M3"].utilization_pct is None


def test_changeover_minutes_none_when_not_modelled_and_summed_when_modelled():
    assert mt.changeover_minutes(SNAP, ASSIGN) is None
    snap = make_snapshot(
        [("O1", 0, 500)],
        {"M1": [(0, 500)]},
        [("A", "O1", [], {"M1": 10}, "X"), ("B", "O1", [], {"M1": 10}, "Y")],
        horizon=500,
        setup={("X", "Y"): 15, ("Y", "X"): 25, ("X", "X"): 0, ("Y", "Y"): 0},
    )
    assert mt.changeover_minutes(snap, [sched("A", "O1", "M1", 0, 10), sched("B", "O1", "M1", 25, 35)]) == 15


def test_schedule_metrics_dict_consistent():
    m = mt.schedule_metrics(SNAP, ASSIGN)
    assert m["late_orders"] == 1 and m["total_tardiness"] == 10 and m["makespan"] == 50
    assert m["total_processing_minutes"] == 80
    assert m["changeover_minutes"] is None
