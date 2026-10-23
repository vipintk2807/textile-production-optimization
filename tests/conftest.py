"""Shared fixtures. All data here is small, hand-checkable and SYNTHETIC (test fixtures only)."""

from __future__ import annotations

import pytest

from textile_optimizer.domain.snapshot import (
    CandidateSchedule,
    MachineSpec,
    OperationSpec,
    OrderSpec,
    ProblemSnapshot,
    ScheduledOperation,
)
from textile_optimizer.persistence.repository import Repository
from textile_optimizer.scheduling.solver import SolverConfig
from textile_optimizer.services.planning_service import PlanningService

FAST = SolverConfig(time_limit_seconds=10, workers=1, random_seed=1)


def make_snapshot(
    orders,
    machines,
    operations,
    *,
    horizon=1000,
    objective="makespan",
    hard_due=False,
    setup=None,
) -> ProblemSnapshot:
    """Shorthand builder.

    orders:     [(id, release, due)] or [(id, release, due, weight)]
    machines:   {id: [(a, b), ...]}  (effective windows)
    operations: [(op_id, order_id, [preds], {machine: duration}, category|None)]
    setup:      {(from, to): minutes}  (enables changeovers)
    """
    return ProblemSnapshot(
        horizon_end=horizon,
        objective=objective,
        enforce_due_dates=hard_due,
        changeover_enabled=setup is not None,
        origin_iso="2026-01-05T08:00:00",
        orders=tuple(OrderSpec(o[0], o[1], o[2], o[3] if len(o) > 3 else None) for o in orders),
        machines=tuple(MachineSpec(m, tuple(w)) for m, w in machines.items()),
        operations=tuple(
            OperationSpec(
                op[0], op[1], tuple(op[2]), tuple(sorted(op[3].items())), op[4] if len(op) > 4 else None
            )
            for op in operations
        ),
        setup=tuple((a, b, m) for (a, b), m in sorted((setup or {}).items())),
    )


def sched(op, order, machine, start, end, duration=None) -> ScheduledOperation:
    return ScheduledOperation(op, order, machine, start, end, end - start if duration is None else duration)


def cand(*items, **claims) -> CandidateSchedule:
    return CandidateSchedule(assignments=list(items), **claims)


@pytest.fixture
def repo(tmp_path) -> Repository:
    return Repository(tmp_path / "test.db")


@pytest.fixture
def service(repo) -> PlanningService:
    return PlanningService(repo)


@pytest.fixture
def fast_config() -> SolverConfig:
    return FAST
