"""Regression and cross-check tests.

The brute-force comparison is an *independent* verification of the CP-SAT model: it enumerates
every machine assignment and every precedence-feasible operation order of tiny random
instances (semi-active schedules are optimal for makespan / tardiness) and compares the best
objective with the solver's proven optimum.
"""

import itertools
import random

import pytest

from conftest import FAST, make_snapshot
from textile_optimizer.domain.graph import topological_order
from textile_optimizer.scheduling.solver import SolverStatus, solve
from textile_optimizer.validation.schedule_validator import validate_schedule


def brute_force(snap):
    ops = snap.operation_map()
    orders = snap.order_map()
    ids = sorted(ops)
    best = None
    machine_choices = [[m for m, _ in ops[i].options] for i in ids]
    for assignment in itertools.product(*machine_choices):
        chosen = dict(zip(ids, assignment, strict=True))
        for perm in itertools.permutations(ids):
            pos = {o: k for k, o in enumerate(perm)}
            if any(pos[p] > pos[o] for o in ids for p in ops[o].predecessors):
                continue
            end, machine_last = {}, {}
            for o in perm:
                m = chosen[o]
                dur = ops[o].duration_on(m)
                start = max([orders[ops[o].order_id].release_time] + [end[p] for p in ops[o].predecessors])
                if m in machine_last:
                    prev = machine_last[m]
                    start = max(start, end[prev] + snap.setup_minutes(ops[prev], ops[o]))
                end[o] = start + dur
                machine_last[m] = o
            if snap.objective == "makespan":
                value = max(end.values())
            else:
                value = 0
                for order in snap.orders:
                    c = max(end[t.operation_id] for t in snap.terminal_operations(order.order_id))
                    value += max(0, c - order.due_time)
            best = value if best is None else min(best, value)
    return best


def random_instance(seed, objective, with_setup):
    rng = random.Random(seed)
    machines = {"M1": [(0, 10_000)], "M2": [(0, 10_000)]}
    orders = [(f"O{i}", rng.choice([0, 0, 10]), rng.randint(20, 90)) for i in range(2)]
    ops = []
    cats = ["X", "Y"]
    for oi, order in enumerate(orders):
        n = rng.randint(1, 3) if oi == 0 else rng.randint(1, 2)
        for k in range(n):
            opts = {m: rng.randint(5, 30) for m in rng.sample(["M1", "M2"], rng.randint(1, 2))}
            preds = [f"O{oi}-{k - 1}"] if k > 0 and rng.random() < 0.7 else []
            ops.append((f"O{oi}-{k}", order[0], preds, opts, rng.choice(cats)))
    setup = (
        {("X", "X"): 0, ("Y", "Y"): 0, ("X", "Y"): rng.randint(0, 12), ("Y", "X"): rng.randint(0, 12)}
        if with_setup
        else None
    )
    return make_snapshot(orders, machines, ops, horizon=10_000, objective=objective, setup=setup)


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("objective", ["makespan", "total_tardiness"])
@pytest.mark.parametrize("with_setup", [False, True])
def test_solver_optimum_equals_brute_force(seed, objective, with_setup):
    snap = random_instance(seed, objective, with_setup)
    res = solve(snap, FAST)
    assert res.status == SolverStatus.OPTIMAL
    assert validate_schedule(snap, res.candidate).passed
    assert round(res.objective_value) == brute_force(snap), f"seed={seed}"


def test_topological_order_respects_predecessors():
    order = topological_order(["C", "B", "A"], {"B": ["A"], "C": ["B"]})
    assert order == ["A", "B", "C"]
    with pytest.raises(ValueError):
        topological_order(["A", "B"], {"A": ["B"], "B": ["A"]})


def test_table_timeline_and_csv_agree_for_one_run(service):
    """Schedule table, Gantt bars and CSV must all show the stored assignments (E2E-07)."""
    import csv
    import io

    from textile_optimizer.reporting.export import schedule_csv
    from textile_optimizer.services.sample_data import load_sample_data
    from textile_optimizer.ui.gantt import build_gantt
    from textile_optimizer.ui.run_view import schedule_table

    load_sample_data(service)
    run = service.run_schedule().run
    stored = {(a.operation_id, a.machine_id, a.start, a.end) for a in run.assignments}
    table = schedule_table(run)
    from_table = set(
        zip(table["Operation ID"], table["Machine"], table["Start (min)"], table["Finish (min)"], strict=True)
    )
    from_csv = {
        (r["operation_id"], r["machine_id"], int(r["start_min"]), int(r["end_min"]))
        for r in csv.DictReader(io.StringIO(schedule_csv(run, False)))
    }
    fig = build_gantt(run)
    from_gantt = set()
    for trace in fig.data:
        if trace.name == "Unavailable":
            continue
        for y, length, base, cd in zip(trace.y, trace.x, trace.base, trace.customdata, strict=True):
            from_gantt.add((cd[0], y, int(base), int(base) + int(length)))
    assert stored == from_table == from_csv == from_gantt


def test_no_silent_rounding_of_fractional_minutes():
    from datetime import datetime

    from textile_optimizer.domain.timeutil import to_minutes

    with pytest.raises(ValueError):
        to_minutes(datetime(2026, 1, 5, 8, 0, 59), datetime(2026, 1, 5, 8, 0))


def test_solver_status_never_upgraded_from_feasible(service):
    """FEASIBLE must stay FEASIBLE end to end (never shown as optimal)."""
    from dataclasses import replace

    from helpers import machine, op, order
    from textile_optimizer.services.planning_service import PlanningService

    service.save_machine(machine("M1"), is_new=True)
    service.save_order(order("O1"), is_new=True)
    service.save_operation(op("A", "O1", ("M1",)), is_new=True)
    svc = PlanningService(
        service.repo, solver=lambda s, c: replace(solve(s, c), status=SolverStatus.FEASIBLE)
    )
    run = svc.run_schedule().run
    from textile_optimizer.ui.components import outcome_label

    assert outcome_label(run)[0] == "Feasible"
