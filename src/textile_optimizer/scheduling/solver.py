"""Run CP-SAT on a snapshot and return a structured, *unvalidated* result.

The raw solver output is never treated as an accepted schedule: the planning service passes
the extracted candidate to the independent validator first.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

import ortools
from ortools.sat.python import cp_model

from ..domain.snapshot import CandidateSchedule, ProblemSnapshot, ScheduledOperation
from ..errors import ModelConstructionError, SolverExecutionError
from .model_builder import BuiltModel, build_model


class SolverStatus(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    MODEL_INVALID = "MODEL_INVALID"


_STATUS_MAP = {
    cp_model.OPTIMAL: SolverStatus.OPTIMAL,
    cp_model.FEASIBLE: SolverStatus.FEASIBLE,
    cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
    cp_model.MODEL_INVALID: SolverStatus.MODEL_INVALID,
    cp_model.UNKNOWN: SolverStatus.UNKNOWN,
}


def map_status(cp_status: int) -> SolverStatus:
    """Map the OR-Tools status code to the application status (never upgrades FEASIBLE)."""
    try:
        return _STATUS_MAP[cp_status]
    except KeyError as exc:  # pragma: no cover - defensive: unknown future status code
        raise SolverExecutionError(f"Unrecognised solver status code {cp_status}.") from exc


@dataclass(frozen=True)
class SolverConfig:
    time_limit_seconds: float = 30.0
    workers: int = 1
    random_seed: int = 1


@dataclass
class SolveResult:
    status: SolverStatus
    candidate: CandidateSchedule | None
    objective_value: float | None
    best_bound: float | None
    runtime_seconds: float
    config: SolverConfig
    solver_version: str = field(default_factory=lambda: ortools.__version__)
    model_stats: dict[str, int] = field(default_factory=dict)
    detail: str = ""

    @property
    def stopped_at_time_limit(self) -> bool:
        """Heuristic: search ended without a proof close to the configured time limit."""
        return (
            self.status in (SolverStatus.FEASIBLE, SolverStatus.UNKNOWN)
            and self.runtime_seconds >= 0.9 * self.config.time_limit_seconds
        )


def extract_candidate(built: BuiltModel, solver: cp_model.CpSolver) -> CandidateSchedule:
    """Read assignments and the solver's own completion/tardiness claims from a solution."""
    snapshot = built.snapshot
    assignments: list[ScheduledOperation] = []
    for op in snapshot.operations:
        chosen = [
            m for (o, m), lit in built.presence.items() if o == op.operation_id and solver.boolean_value(lit)
        ]
        if len(chosen) != 1:
            raise SolverExecutionError(
                f"Incomplete solution: operation {op.operation_id} has {len(chosen)} machine(s) selected."
            )
        machine_id = chosen[0]
        start = solver.value(built.start[op.operation_id])
        end = solver.value(built.end[op.operation_id])
        assignments.append(
            ScheduledOperation(op.operation_id, op.order_id, machine_id, start, end, end - start)
        )
    return CandidateSchedule(
        assignments=assignments,
        claimed_completion={oid: solver.value(v) for oid, v in built.completion.items()},
        claimed_tardiness={oid: solver.value(v) for oid, v in built.tardiness.items()},
        claimed_makespan=solver.value(built.makespan) if built.makespan is not None else None,
        claimed_objective=int(round(solver.objective_value)),
    )


def solve(
    snapshot: ProblemSnapshot,
    config: SolverConfig,
    model_hook: Callable[[BuiltModel], None] | None = None,
) -> SolveResult:
    """Build and solve the model. ``model_hook`` lets tests tamper with the model."""
    built = build_model(snapshot)
    if model_hook is not None:
        model_hook(built)
    validation_text = built.model.validate()
    if validation_text:
        return SolveResult(
            SolverStatus.MODEL_INVALID,
            None,
            None,
            None,
            0.0,
            config,
            model_stats=built.stats,
            detail=validation_text,
        )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(config.time_limit_seconds)
    solver.parameters.num_workers = int(config.workers)
    solver.parameters.random_seed = int(config.random_seed)
    started = time.perf_counter()
    try:
        cp_status = solver.solve(built.model)
    except Exception as exc:  # noqa: BLE001 - re-raised as an application error with context
        raise SolverExecutionError(f"The solver raised an unexpected error: {exc}") from exc
    elapsed = time.perf_counter() - started
    status = map_status(cp_status)
    candidate = None
    objective = bound = None
    if status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
        candidate = extract_candidate(built, solver)
        objective = solver.objective_value
        bound = solver.best_objective_bound
    return SolveResult(status, candidate, objective, bound, elapsed, config, model_stats=built.stats)


__all__ = [
    "ModelConstructionError",
    "SolveResult",
    "SolverConfig",
    "SolverStatus",
    "build_model",
    "extract_candidate",
    "map_status",
    "solve",
]
