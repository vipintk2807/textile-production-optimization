"""Solver status mapping, time limits, invalid models and service-level failure handling."""

import time

from ortools.sat.python import cp_model

from conftest import FAST, make_snapshot
from textile_optimizer.scheduling.solver import SolverConfig, SolverStatus, map_status, solve


def test_status_mapping_distinguishes_all_five_outcomes():
    assert map_status(cp_model.OPTIMAL) == SolverStatus.OPTIMAL
    assert map_status(cp_model.FEASIBLE) == SolverStatus.FEASIBLE
    assert map_status(cp_model.INFEASIBLE) == SolverStatus.INFEASIBLE
    assert map_status(cp_model.UNKNOWN) == SolverStatus.UNKNOWN
    assert map_status(cp_model.MODEL_INVALID) == SolverStatus.MODEL_INVALID
    assert len({map_status(s) for s in (0, 1, 2, 3, 4)}) == 5  # no two outcomes collapse together


def test_invalid_model_is_reported_as_model_invalid_not_infeasible():
    snap = make_snapshot([("O1", 0, 100)], {"M1": [(0, 500)]}, [("A", "O1", [], {"M1": 30})], horizon=500)

    def tamper(built):
        x = built.model.new_int_var(0, 2**62, "big")
        built.model.add(x * 4 + x * 4 >= 0)

    res = solve(snap, FAST, model_hook=tamper)
    assert res.status == SolverStatus.MODEL_INVALID and res.candidate is None and res.detail


def _hard_instance(n_orders=14):
    """Larger synthetic job-shop instance used to exercise the time limit."""
    machines = {f"M{i}": [(0, 100000)] for i in range(3)}
    orders = [(f"O{i}", 0, 50 + 7 * i) for i in range(n_orders)]
    ops = []
    for i in range(n_orders):
        ops.append((f"A{i}", f"O{i}", [], {"M0": 11 + i % 5, "M1": 13 + i % 4}))
        ops.append((f"B{i}", f"O{i}", [f"A{i}"], {"M1": 9 + i % 3, "M2": 14 + i % 6}))
        ops.append((f"C{i}", f"O{i}", [f"B{i}"], {"M0": 7 + i % 7, "M2": 10 + i % 2}))
    return make_snapshot(orders, machines, ops, horizon=100000, objective="total_tardiness")


def test_time_limit_is_passed_to_solver_and_respected():
    snap = _hard_instance()
    cfg = SolverConfig(time_limit_seconds=0.5, workers=1, random_seed=1)
    started = time.perf_counter()
    res = solve(snap, cfg)
    wall = time.perf_counter() - started
    assert res.config.time_limit_seconds == 0.5 and res.runtime_seconds <= wall
    assert wall < 10  # generous bound: only checks the limit stopped a long search
    # a time limit is neither proof of infeasibility nor of optimality
    assert res.status in (SolverStatus.FEASIBLE, SolverStatus.UNKNOWN, SolverStatus.OPTIMAL)
    if res.status == SolverStatus.FEASIBLE:
        assert res.candidate is not None and res.stopped_at_time_limit
    if res.status == SolverStatus.UNKNOWN:
        assert res.candidate is None  # no candidate is assumed to exist


def test_time_limited_feasible_candidate_passes_independent_validation():
    from textile_optimizer.validation.schedule_validator import validate_schedule

    snap = _hard_instance(14)
    res = solve(snap, SolverConfig(time_limit_seconds=0.5, workers=1, random_seed=1))
    assert res.status != SolverStatus.INFEASIBLE  # a time limit must never be reported as infeasibility
    if res.candidate is not None:
        assert validate_schedule(snap, res.candidate).passed
