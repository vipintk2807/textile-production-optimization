"""Application service layer: coordinates validation, persistence, solving and acceptance.

All business rules live here or below; the Streamlit pages only call this class. The solver
is injectable so tests can simulate failures and corrupted candidates.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeVar

import ortools
from pydantic import BaseModel, ValidationError

from .. import MODEL_VERSION, __version__
from ..domain.graph import find_cycle
from ..domain.intervals import find_overlapping_pairs
from ..domain.models import (
    ChangeoverRule,
    MachineRecord,
    OperationRecord,
    OrderRecord,
    PlanningSettings,
)
from ..domain.snapshot import PlanningData, ProblemSnapshot, compile_snapshot
from ..errors import (
    InputValidationError,
    IntegrityConflictError,
    PersistenceError,
    RunInProgressError,
    TextileOptimizerError,
)
from ..logging_setup import get_logger
from ..persistence.repository import Repository, StoredRun
from ..reporting.metrics import schedule_metrics
from ..scheduling.baseline import BaselineResult, run_baseline
from ..scheduling.solver import SolverConfig, SolveResult, SolverStatus, solve
from ..validation.input_validation import validate_inputs
from ..validation.report import ValidationReport
from ..validation.schedule_validator import validate_schedule

log = get_logger("service")

T = TypeVar("T", bound=BaseModel)

# application-level run outcomes (superset of the persisted outcomes)
INPUT_INVALID = "INPUT_INVALID"


def build_record(model: type[T], **fields) -> T:
    """Construct a Pydantic record; convert validation errors to actionable messages."""
    try:
        return model(**fields)
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "record"
            msg = err["msg"].removeprefix("Value error, ")
            messages.append(f"{loc}: {msg}" if err["loc"] else msg)
        raise InputValidationError(messages) from exc


@dataclass
class RunResult:
    outcome: (
        str  # INPUT_INVALID | ACCEPTED | INFEASIBLE | NO_SOLUTION | MODEL_INVALID | VALIDATION_FAILED | ERROR
    )
    message: str
    run: StoredRun | None = None
    input_report: ValidationReport = field(default_factory=ValidationReport)

    @property
    def accepted(self) -> bool:
        return self.outcome == "ACCEPTED"


class PlanningService:
    _run_lock = threading.Lock()  # one scheduling run at a time per process

    def __init__(
        self,
        repo: Repository,
        solver: Callable[[ProblemSnapshot, SolverConfig], SolveResult] = solve,
    ):
        self.repo = repo
        self._solver = solver

    # ------------------------------------------------------------------ data access
    def load_data(self) -> PlanningData:
        return PlanningData(
            orders=self.repo.list_orders(),
            machines=self.repo.list_machines(),
            operations=self.repo.list_operations(),
            changeover_rules=self.repo.list_changeover_rules(),
            settings=self.repo.get_settings(),
        )

    # ------------------------------------------------------------------ orders
    def save_order(self, order: OrderRecord, *, is_new: bool) -> None:
        if is_new:
            self.repo.insert_order(order)
        else:
            self.repo.update_order(order)
        log.info("order saved id=%s new=%s", order.order_id, is_new)

    def delete_order(self, order_id: str) -> int:
        removed = self.repo.delete_order(order_id)
        log.info("order deleted id=%s operations_removed=%d", order_id, removed)
        return removed

    # ------------------------------------------------------------------ machines
    def save_machine(self, machine: MachineRecord, *, is_new: bool) -> None:
        problems: list[str] = []
        for pair in find_overlapping_pairs([i.as_tuple() for i in machine.availability]):
            problems.append(f"Availability windows {list(pair[0])} and {list(pair[1])} overlap.")
        for pair in find_overlapping_pairs([i.as_tuple() for i in machine.downtime]):
            problems.append(f"Downtime intervals {list(pair[0])} and {list(pair[1])} overlap.")
        if problems:
            raise InputValidationError(problems)
        if is_new:
            self.repo.insert_machine(machine)
        else:
            self.repo.update_machine(machine)
        log.info("machine saved id=%s new=%s", machine.machine_id, is_new)

    def delete_machine(self, machine_id: str) -> None:
        self.repo.delete_machine(machine_id)
        log.info("machine deleted id=%s", machine_id)

    # ------------------------------------------------------------------ operations
    def save_operation(self, op: OperationRecord, *, is_new: bool) -> None:
        problems = self.check_operation(op)
        if problems:
            raise InputValidationError(problems)
        if is_new:
            self.repo.insert_operation(op)
        else:
            self.repo.update_operation(op)
        log.info("operation saved id=%s new=%s", op.operation_id, is_new)

    def check_operation(self, op: OperationRecord) -> list[str]:
        """Cross-record checks for one operation (references, capabilities, cycles)."""
        problems: list[str] = []
        orders = {o.order_id for o in self.repo.list_orders()}
        machines = {m.machine_id: m for m in self.repo.list_machines()}
        all_ops = {o.operation_id: o for o in self.repo.list_operations()}
        if op.order_id not in orders:
            problems.append(f"Parent order '{op.order_id}' does not exist.")
        if not op.eligible_machines:
            problems.append("Select at least one eligible machine.")
        for em in op.eligible_machines:
            machine = machines.get(em.machine_id)
            if machine is None:
                problems.append(f"Eligible machine '{em.machine_id}' does not exist.")
            elif op.operation_name not in machine.supported_processes:
                problems.append(
                    f"Machine {em.machine_id} does not list '{op.operation_name}' among its "
                    "supported processes."
                )
        for pred in op.predecessors:
            pred_op = all_ops.get(pred)
            if pred_op is None:
                problems.append(f"Predecessor '{pred}' does not exist.")
            elif pred_op.order_id != op.order_id:
                problems.append(
                    f"Predecessor {pred} belongs to another order (cross-order dependencies are unsupported)."
                )
        if not problems:
            graph = {oid: list(o.predecessors) for oid, o in all_ops.items()}
            graph[op.operation_id] = list(op.predecessors)
            cycle = find_cycle(graph.keys(), graph)
            if cycle:
                problems.append("These predecessors create a dependency cycle: " + " -> ".join(cycle) + ".")
        return problems

    def delete_operation(self, operation_id: str) -> None:
        self.repo.delete_operation(operation_id)
        log.info("operation deleted id=%s", operation_id)

    # ------------------------------------------------------------------ settings / changeovers
    def save_settings(self, settings: PlanningSettings) -> None:
        self.repo.save_settings(settings)

    def save_changeover_rules(self, rules: list[ChangeoverRule]) -> None:
        seen = set()
        for r in rules:
            key = (r.from_category, r.to_category)
            if key in seen:
                raise InputValidationError(f"Duplicate changeover rule {r.from_category} -> {r.to_category}.")
            seen.add(key)
        self.repo.replace_changeover_rules(rules)

    # ------------------------------------------------------------------ validation / snapshot
    def validate_inputs(self) -> ValidationReport:
        return validate_inputs(self.load_data())

    def current_snapshot(self) -> ProblemSnapshot:
        """Snapshot of the saved data right now (may be incomplete if inputs are invalid)."""
        return compile_snapshot(self.load_data())

    def current_fingerprint(self) -> str:
        return self.current_snapshot().fingerprint()

    def is_stale(self, run: StoredRun | None) -> bool:
        """True when scheduling-relevant data or objective configuration changed since the run."""
        if run is None:
            return False
        return run.input_fingerprint != self.current_fingerprint()

    def baseline_for(self, run: StoredRun) -> BaselineResult:
        """Baseline schedule on the *run's own* input snapshot (identical data for comparison)."""
        return run_baseline(run.snapshot)

    # ------------------------------------------------------------------ scheduling
    def run_schedule(self) -> RunResult:
        """Validate, solve, independently validate and persist. Never raises for expected failures."""
        if not self._run_lock.acquire(blocking=False):
            raise RunInProgressError("A scheduling run is already in progress. Wait for it to finish.")
        try:
            return self._run_locked()
        finally:
            self._run_lock.release()

    def _run_locked(self) -> RunResult:
        data = self.load_data()
        report = validate_inputs(data)
        if not report.passed:
            log.info("run blocked: %d input error(s)", len(report.errors))
            return RunResult(
                INPUT_INVALID,
                f"The inputs have {len(report.errors)} blocking error(s). The solver was not run.",
                None,
                report,
            )
        snapshot = compile_snapshot(data)
        fingerprint = snapshot.fingerprint()
        settings = data.settings
        config = SolverConfig(settings.time_limit_seconds, settings.workers, settings.random_seed)
        synthetic = all(o.is_synthetic for o in data.orders if o.order_id in snapshot.order_map())

        base = dict(
            created_at=datetime.now().isoformat(timespec="seconds"),
            objective=snapshot.objective,
            time_limit=config.time_limit_seconds,
            workers=config.workers,
            random_seed=config.random_seed,
            app_version=__version__,
            model_version=MODEL_VERSION,
            input_fingerprint=fingerprint,
            snapshot=snapshot,
            is_synthetic_data=synthetic,
        )

        try:
            result = self._solver(snapshot, config)
        except TextileOptimizerError as exc:
            return self._record_error(base, report, f"Scheduling failed: {exc}", exc)
        except Exception as exc:  # noqa: BLE001 - logged with traceback, reported as ERROR
            return self._record_error(base, report, "Unexpected error while scheduling.", exc)

        solver_fields = dict(
            solver_status=result.status.value,
            objective_value=result.objective_value,
            best_bound=result.best_bound,
            runtime_seconds=result.runtime_seconds,
            stopped_at_limit=result.stopped_at_time_limit,
            solver_version=result.solver_version,
            model_stats=result.model_stats,
            detail=result.detail,
        )

        if result.status == SolverStatus.INFEASIBLE:
            run = self._persist(
                StoredRun(run_id=0, outcome="INFEASIBLE", accepted=False, **base, **solver_fields)
            )
            return RunResult(
                "INFEASIBLE",
                "The solver proved that no schedule satisfies all encoded constraints "
                f"for this horizon ({snapshot.horizon_end} min). This is different from "
                "a feasible schedule with late orders.",
                run,
                report,
            )
        if result.status == SolverStatus.MODEL_INVALID:
            run = self._persist(
                StoredRun(run_id=0, outcome="MODEL_INVALID", accepted=False, **base, **solver_fields)
            )
            return RunResult(
                "MODEL_INVALID",
                "The optimization model was rejected as invalid (a model error, not "
                f"an infeasible production problem). {result.detail}",
                run,
                report,
            )
        if result.status == SolverStatus.UNKNOWN or result.candidate is None:
            run = self._persist(
                StoredRun(run_id=0, outcome="NO_SOLUTION", accepted=False, **base, **solver_fields)
            )
            return RunResult(
                "NO_SOLUTION",
                "No feasible solution was found within the time limit and infeasibility "
                "was not proven. This does not mean no schedule exists - try a longer "
                "time limit.",
                run,
                report,
            )

        # OPTIMAL or FEASIBLE: the candidate must pass independent validation before acceptance
        validation = validate_schedule(snapshot, result.candidate)
        if not validation.passed:
            run = self._persist(
                StoredRun(
                    run_id=0,
                    outcome="VALIDATION_FAILED",
                    accepted=False,
                    assignments=list(result.candidate.assignments),
                    validation_issues=validation.issues,
                    **base,
                    **solver_fields,
                )
            )
            log.error("candidate failed validation run=%s errors=%d", run.run_id, len(validation.errors))
            return RunResult(
                "VALIDATION_FAILED",
                "The solver returned a candidate that failed independent validation; "
                "it was rejected and is NOT an accepted schedule.",
                run,
                report,
            )

        metrics = schedule_metrics(snapshot, result.candidate.assignments)
        run = self._persist(
            StoredRun(
                run_id=0,
                outcome="ACCEPTED",
                accepted=True,
                assignments=list(result.candidate.assignments),
                validation_issues=validation.issues,
                metrics=metrics,
                **base,
                **solver_fields,
            )
        )
        proven = result.status == SolverStatus.OPTIMAL
        log.info(
            "run accepted id=%s status=%s runtime=%.2fs fingerprint=%s",
            run.run_id,
            result.status.value,
            result.runtime_seconds,
            fingerprint[:12],
        )
        return RunResult(
            "ACCEPTED",
            "Schedule validated. Optimality was proven for the configured objective."
            if proven
            else "Schedule validated. A feasible solution was found but optimality was NOT proven.",
            run,
            report,
        )

    def _persist(self, run: StoredRun) -> StoredRun:
        run.run_id = self.repo.insert_run(run)  # raises PersistenceError; transaction rolled back
        return self.repo.get_run(run.run_id) or run

    def _record_error(self, base: dict, report: ValidationReport, message: str, exc: Exception) -> RunResult:
        log.error("run failed: %s", message, exc_info=exc)
        stored: StoredRun | None = None
        try:
            stored = self._persist(
                StoredRun(
                    run_id=0,
                    outcome="ERROR",
                    accepted=False,
                    solver_status=None,
                    objective_value=None,
                    best_bound=None,
                    runtime_seconds=None,
                    stopped_at_limit=False,
                    solver_version=ortools.__version__,
                    model_stats={},
                    detail=str(exc)[:500],
                    **base,
                )
            )
        except PersistenceError:
            log.exception("could not record failed run")
        return RunResult("ERROR", message, stored, report)


__all__ = [
    "INPUT_INVALID",
    "IntegrityConflictError",
    "PlanningService",
    "RunResult",
    "build_record",
]
