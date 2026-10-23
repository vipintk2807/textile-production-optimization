"""End-to-end service workflow tests (E2E-01 .. E2E-07). Real solver, real SQLite."""

import csv
import io
from dataclasses import replace

import pytest

from helpers import machine, op, order
from textile_optimizer.domain.models import Objective, PlanningSettings
from textile_optimizer.errors import PersistenceError, RunInProgressError, SolverExecutionError
from textile_optimizer.persistence.repository import Repository
from textile_optimizer.reporting import export
from textile_optimizer.scheduling.solver import SolveResult, SolverStatus, solve
from textile_optimizer.services.planning_service import PlanningService


def basic_setup(service, due=500, objective="total_tardiness"):
    service.save_machine(machine("M1", windows=((0, 400), (500, 900))), is_new=True)
    service.save_machine(machine("M2"), is_new=True)
    service.save_order(order("O1", due_time=due), is_new=True)
    service.save_order(order("O2", due_time=due), is_new=True)
    service.save_operation(op("A", "O1", ("M1", "M2")), is_new=True)
    service.save_operation(op("B", "O1", ("M1", "M2"), preds=("A",)), is_new=True)
    service.save_operation(op("C", "O2", ("M1", "M2")), is_new=True)
    service.save_settings(PlanningSettings(horizon_end=1000, objective=objective, time_limit_seconds=10))


def test_e2e_01_valid_workflow_saves_validated_schedule(service):
    basic_setup(service)
    assert service.validate_inputs().passed
    result = service.run_schedule()
    assert result.outcome == "ACCEPTED" and result.run.accepted
    run = service.repo.get_run(result.run.run_id)  # reload from SQLite
    assert run.solver_status == "OPTIMAL" and len(run.assignments) == 3
    assert run.metrics["scheduled_operations"] == 3 and run.metrics["total_tardiness"] == 0
    assert run.input_fingerprint == service.current_fingerprint()
    assert run.snapshot.fingerprint() == run.input_fingerprint  # snapshot stored with the run
    assert not service.is_stale(run)


def test_e2e_02_invalid_input_never_reaches_solver(service):
    basic_setup(service)
    service.repo.update_machine(machine("M2", windows=()))  # M2 used but no availability
    service.repo.update_machine(machine("M1", windows=()))
    called = []
    svc = PlanningService(service.repo, solver=lambda s, c: called.append(1))
    result = svc.run_schedule()
    assert result.outcome == "INPUT_INVALID" and not called and result.run is None
    assert service.repo.counts()["runs"] == 0  # nothing persisted, no schedule accepted


def test_e2e_03_infeasible_is_distinct_from_late(service):
    basic_setup(service, due=10)  # tight due dates: feasible-but-late
    late = service.run_schedule()
    assert late.outcome == "ACCEPTED" and late.run.metrics["late_orders"] >= 1
    s = service.repo.get_settings()
    service.save_settings(s.model_copy(update={"enforce_due_dates": True}))  # same data, hard due dates
    result = service.run_schedule()
    assert result.outcome == "INFEASIBLE" and not result.run.accepted
    assert result.run.assignments == [] and "proved" in result.message


def test_e2e_04_feasible_but_not_optimal_is_labelled_feasible(service):
    basic_setup(service)

    def feasible_only(snapshot, cfg):
        real = solve(snapshot, cfg)
        return replace(real, status=SolverStatus.FEASIBLE)  # solver "stopped" before proving optimality

    result = PlanningService(service.repo, solver=feasible_only).run_schedule()
    assert result.outcome == "ACCEPTED" and result.run.solver_status == "FEASIBLE"
    assert "NOT proven" in result.message  # never advertised as optimal


def test_e2e_05_stale_after_relevant_change_but_not_display_only(service):
    basic_setup(service)
    run = service.run_schedule().run
    service.save_order(order("O1", due_time=500, description="only a label changed", notes="x"), is_new=False)
    assert not service.is_stale(run)  # display-only change
    service.save_order(order("O1", due_time=501), is_new=False)
    assert service.is_stale(run)  # due time changed
    service.save_order(order("O1", due_time=500), is_new=False)
    assert not service.is_stale(run)  # changed back: identical scheduling inputs again
    service.save_machine(machine("M2", windows=((0, 900),)), is_new=False)
    assert service.is_stale(run)
    # the historical run is still available and keeps its own snapshot/metrics
    old = service.repo.get_run(run.run_id)
    assert old.metrics == run.metrics and old.snapshot.horizon_end == 1000


def test_objective_change_makes_previous_result_stale(service):
    basic_setup(service)
    run = service.run_schedule().run
    service.save_settings(service.repo.get_settings().model_copy(update={"objective": Objective.MAKESPAN}))
    assert service.is_stale(run)


def test_e2e_06_failed_runs_never_overwrite_last_validated_schedule(service):
    basic_setup(service)
    good = service.run_schedule().run

    def exploding(snapshot, cfg):
        raise SolverExecutionError("simulated solver crash")

    failed = PlanningService(service.repo, solver=exploding).run_schedule()
    assert failed.outcome == "ERROR" and failed.run is not None and not failed.run.accepted

    def corrupt(snapshot, cfg):
        real = solve(snapshot, cfg)
        a = real.candidate.assignments
        # force every operation onto M2 at minute 0 so the candidate certainly overlaps
        real.candidate.assignments = [replace(x, machine_id="M2", start=0, end=x.duration) for x in a]
        return real

    rejected = PlanningService(service.repo, solver=corrupt).run_schedule()
    assert rejected.outcome == "VALIDATION_FAILED" and not rejected.run.accepted
    assert any(i.code == "VAL_OVERLAP" for i in rejected.run.validation_issues)
    assert rejected.run.metrics is None  # metrics only exist for accepted schedules

    unknown = PlanningService(
        service.repo, solver=lambda s, c: SolveResult(SolverStatus.UNKNOWN, None, None, None, 10.0, c)
    ).run_schedule()
    assert unknown.outcome == "NO_SOLUTION" and "does not mean no schedule exists" in unknown.message

    latest = service.repo.latest_accepted_run()
    assert latest.run_id == good.run_id and latest.metrics == good.metrics  # untouched
    assert service.repo.counts()["runs"] == 4  # failed attempts kept for debugging, clearly flagged


def test_persistence_failure_during_save_leaves_no_misleading_record(service, monkeypatch):
    basic_setup(service)
    before = service.repo.counts()["runs"]

    def broken_insert(self, run):
        raise PersistenceError("simulated write failure")

    monkeypatch.setattr(Repository, "insert_run", broken_insert)
    with pytest.raises(PersistenceError):
        service.run_schedule()
    monkeypatch.undo()
    assert service.repo.counts()["runs"] == before and service.repo.latest_accepted_run() is None


def test_e2e_07_reporting_consistency_and_csv_export(service):
    basic_setup(service)
    run = service.run_schedule().run
    stale = service.is_stale(run)
    rows = list(csv.DictReader(io.StringIO(export.schedule_csv(run, stale))))
    assert len(rows) == len(run.assignments) == 3
    by_op = {r["operation_id"]: r for r in rows}
    for a in run.assignments:  # export equals stored assignments
        r = by_op[a.operation_id]
        assert (r["machine_id"], int(r["start_min"]), int(r["end_min"]), int(r["duration_min"])) == (
            a.machine_id,
            a.start,
            a.end,
            a.duration,
        )
        assert r["run_id"] == str(run.run_id) and r["run_status"] == "VALIDATED_CURRENT"
    service.save_order(order("O1", due_time=999), is_new=False)
    stale_rows = list(csv.DictReader(io.StringIO(export.schedule_csv(run, service.is_stale(run)))))
    assert stale_rows[0]["run_status"] == "VALIDATED_STALE_HISTORICAL"  # stale is never exported as current
    util = export.machine_utilization_rows(run)
    assert {u["machine_id"] for u in util} == {"M1", "M2"}


def test_csv_writer_handles_commas_quotes_and_non_ascii():
    text = export._to_csv([{"id": 'A "x", y', "note": "caf\u00e9 \u7e5e\u7269"}])
    row = next(csv.DictReader(io.StringIO(text)))
    assert row == {"id": 'A "x", y', "note": "caf\u00e9 \u7e5e\u7269"}


def test_duplicate_run_prevention(service):
    basic_setup(service)
    assert PlanningService._run_lock.acquire(blocking=False)
    try:
        with pytest.raises(RunInProgressError):
            service.run_schedule()
        assert service.repo.counts()["runs"] == 0  # a blocked request created no run
    finally:
        PlanningService._run_lock.release()
    assert service.run_schedule().accepted  # lock released: normal run works


def test_each_run_has_its_own_id_and_history_is_kept(service):
    basic_setup(service)
    r1, r2 = service.run_schedule().run, service.run_schedule().run
    assert r1.run_id != r2.run_id and len(service.repo.list_runs()) == 2
    assert r1.input_fingerprint == r2.input_fingerprint


def test_baseline_comparison_uses_identical_snapshot_and_is_valid(service):
    basic_setup(service)
    run = service.run_schedule().run
    base = service.baseline_for(run)
    assert base.valid and len(base.candidate.assignments) == 3
    from textile_optimizer.reporting.metrics import schedule_metrics

    assert (
        schedule_metrics(run.snapshot, base.candidate.assignments)["total_tardiness"]
        >= run.metrics["total_tardiness"]
    )


def test_synthetic_sample_data_loads_and_schedules(service):
    from textile_optimizer.errors import IntegrityConflictError
    from textile_optimizer.services.sample_data import SAMPLE_LABEL, load_sample_data

    load_sample_data(service)
    assert all(o.is_synthetic and o.order_id.startswith("SYN-") for o in service.repo.list_orders())
    assert all(m.is_synthetic for m in service.repo.list_machines())
    assert service.repo.get_settings().dataset_label == SAMPLE_LABEL
    result = service.run_schedule()
    assert result.outcome == "ACCEPTED" and result.run.is_synthetic_data
    with pytest.raises(IntegrityConflictError):  # never mixes with / overwrites user data
        load_sample_data(service)
