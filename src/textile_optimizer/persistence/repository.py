"""CRUD access to SQLite. All SQL is parameterised; every write is one transaction."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..domain.models import (
    ChangeoverRule,
    EligibleMachine,
    IntervalRecord,
    MachineRecord,
    OperationRecord,
    OrderRecord,
    PlanningSettings,
)
from ..domain.snapshot import ProblemSnapshot, ScheduledOperation
from ..errors import IntegrityConflictError, PersistenceError
from ..validation.report import Issue
from .db import connect, init_db, transaction

OUTCOMES = (
    "ACCEPTED",
    "INFEASIBLE",
    "NO_SOLUTION",
    "MODEL_INVALID",
    "VALIDATION_FAILED",
    "ERROR",
)


@dataclass
class StoredRun:
    """A persisted scheduling run, reconstructed exactly as it was saved."""

    run_id: int
    created_at: str
    outcome: str
    solver_status: str | None
    accepted: bool
    objective: str
    objective_value: float | None
    best_bound: float | None
    time_limit: float
    workers: int
    random_seed: int
    runtime_seconds: float | None
    stopped_at_limit: bool
    solver_version: str
    model_version: str
    app_version: str
    input_fingerprint: str
    snapshot: ProblemSnapshot
    assignments: list[ScheduledOperation] = field(default_factory=list)
    validation_issues: list[Issue] = field(default_factory=list)
    metrics: dict | None = None
    model_stats: dict = field(default_factory=dict)
    detail: str = ""
    is_synthetic_data: bool = False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repository:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        init_db(self.path)

    # ------------------------------------------------------------------ helpers
    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = connect(self.path)
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Database read failed: {exc}") from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------ orders
    def list_orders(self) -> list[OrderRecord]:
        return [self._order(r) for r in self._read("SELECT * FROM orders ORDER BY order_id")]

    def get_order(self, order_id: str) -> OrderRecord | None:
        rows = self._read("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        return self._order(rows[0]) if rows else None

    @staticmethod
    def _order(r: sqlite3.Row) -> OrderRecord:
        return OrderRecord(
            order_id=r["order_id"],
            product_code=r["product_code"],
            description=r["description"],
            quantity=r["quantity"],
            quantity_unit=r["quantity_unit"],
            release_time=r["release_time"],
            due_time=r["due_time"],
            priority=r["priority"],
            weight=r["weight"],
            status=r["status"],
            notes=r["notes"],
            is_synthetic=bool(r["is_synthetic"]),
        )

    def insert_order(self, o: OrderRecord) -> None:
        try:
            with transaction(self.path) as conn:
                conn.execute(
                    "INSERT INTO orders (order_id, product_code, description, quantity, quantity_unit,"
                    " release_time, due_time, priority, weight, status, notes, is_synthetic, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        o.order_id,
                        o.product_code,
                        o.description,
                        o.quantity,
                        o.quantity_unit,
                        o.release_time,
                        o.due_time,
                        o.priority,
                        o.weight,
                        o.status.value,
                        o.notes,
                        int(o.is_synthetic),
                        _now(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc) or "PRIMARY" in str(exc):
                raise IntegrityConflictError(f"Order ID '{o.order_id}' already exists.") from exc
            raise PersistenceError(f"Order could not be saved: {exc}") from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Order could not be saved: {exc}") from exc

    def update_order(self, o: OrderRecord) -> None:
        try:
            with transaction(self.path) as conn:
                cur = conn.execute(
                    "UPDATE orders SET product_code=?, description=?, quantity=?, quantity_unit=?,"
                    " release_time=?, due_time=?, priority=?, weight=?, status=?, notes=?,"
                    " is_synthetic=?, updated_at=? WHERE order_id=?",
                    (
                        o.product_code,
                        o.description,
                        o.quantity,
                        o.quantity_unit,
                        o.release_time,
                        o.due_time,
                        o.priority,
                        o.weight,
                        o.status.value,
                        o.notes,
                        int(o.is_synthetic),
                        _now(),
                        o.order_id,
                    ),
                )
                if cur.rowcount == 0:
                    raise IntegrityConflictError(f"Order '{o.order_id}' does not exist.")
        except sqlite3.Error as exc:
            raise PersistenceError(f"Order could not be saved: {exc}") from exc

    def delete_order(self, order_id: str) -> int:
        """Delete an order and (by cascade) its operations. Returns the operation count removed."""
        try:
            with transaction(self.path) as conn:
                n_ops = conn.execute(
                    "SELECT COUNT(*) FROM operations WHERE order_id = ?", (order_id,)
                ).fetchone()[0]
                cur = conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
                if cur.rowcount == 0:
                    raise IntegrityConflictError(f"Order '{order_id}' does not exist.")
                return n_ops
        except sqlite3.Error as exc:
            raise PersistenceError(f"Order could not be deleted: {exc}") from exc

    # ------------------------------------------------------------------ machines
    def list_machines(self) -> list[MachineRecord]:
        rows = self._read("SELECT * FROM machines ORDER BY machine_id")
        caps: dict[str, list[str]] = {}
        for r in self._read("SELECT machine_id, process FROM machine_capabilities ORDER BY process"):
            caps.setdefault(r["machine_id"], []).append(r["process"])
        ivs: dict[tuple[str, str], list[IntervalRecord]] = {}
        for r in self._read(
            "SELECT machine_id, kind, start_time, end_time FROM machine_intervals"
            " ORDER BY start_time, end_time"
        ):
            ivs.setdefault((r["machine_id"], r["kind"]), []).append(
                IntervalRecord(start=r["start_time"], end=r["end_time"])
            )
        return [
            MachineRecord(
                machine_id=r["machine_id"],
                machine_name=r["machine_name"],
                machine_type=r["machine_type"],
                supported_processes=caps.get(r["machine_id"]) or ["(none)"],
                status=r["status"],
                notes=r["notes"],
                availability=ivs.get((r["machine_id"], "available"), []),
                downtime=ivs.get((r["machine_id"], "downtime"), []),
                is_synthetic=bool(r["is_synthetic"]),
            )
            for r in rows
        ]

    def get_machine(self, machine_id: str) -> MachineRecord | None:
        return next((m for m in self.list_machines() if m.machine_id == machine_id), None)

    def _write_machine_children(self, conn: sqlite3.Connection, m: MachineRecord) -> None:
        conn.execute("DELETE FROM machine_capabilities WHERE machine_id = ?", (m.machine_id,))
        conn.execute("DELETE FROM machine_intervals WHERE machine_id = ?", (m.machine_id,))
        conn.executemany(
            "INSERT INTO machine_capabilities (machine_id, process) VALUES (?, ?)",
            [(m.machine_id, p) for p in m.supported_processes],
        )
        rows = [(m.machine_id, "available", i.start, i.end) for i in m.availability] + [
            (m.machine_id, "downtime", i.start, i.end) for i in m.downtime
        ]
        conn.executemany(
            "INSERT INTO machine_intervals (machine_id, kind, start_time, end_time) VALUES (?,?,?,?)",
            rows,
        )

    def insert_machine(self, m: MachineRecord) -> None:
        try:
            with transaction(self.path) as conn:
                conn.execute(
                    "INSERT INTO machines (machine_id, machine_name, machine_type, status, notes,"
                    " is_synthetic, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        m.machine_id,
                        m.machine_name,
                        m.machine_type,
                        m.status.value,
                        m.notes,
                        int(m.is_synthetic),
                        _now(),
                    ),
                )
                self._write_machine_children(conn, m)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc) or "PRIMARY" in str(exc):
                raise IntegrityConflictError(f"Machine ID '{m.machine_id}' already exists.") from exc
            raise PersistenceError(f"Machine could not be saved: {exc}") from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Machine could not be saved: {exc}") from exc

    def update_machine(self, m: MachineRecord) -> None:
        try:
            with transaction(self.path) as conn:
                cur = conn.execute(
                    "UPDATE machines SET machine_name=?, machine_type=?, status=?, notes=?,"
                    " is_synthetic=?, updated_at=? WHERE machine_id=?",
                    (
                        m.machine_name,
                        m.machine_type,
                        m.status.value,
                        m.notes,
                        int(m.is_synthetic),
                        _now(),
                        m.machine_id,
                    ),
                )
                if cur.rowcount == 0:
                    raise IntegrityConflictError(f"Machine '{m.machine_id}' does not exist.")
                self._write_machine_children(conn, m)
        except sqlite3.Error as exc:
            raise PersistenceError(f"Machine could not be saved: {exc}") from exc

    def operations_using_machine(self, machine_id: str) -> list[str]:
        return [
            r["operation_id"]
            for r in self._read(
                "SELECT operation_id FROM operation_machines WHERE machine_id = ? ORDER BY operation_id",
                (machine_id,),
            )
        ]

    def delete_machine(self, machine_id: str) -> None:
        users = self.operations_using_machine(machine_id)
        if users:
            raise IntegrityConflictError(
                f"Machine {machine_id} is an eligible machine of {len(users)} operation(s) "
                f"({', '.join(users[:8])}{'...' if len(users) > 8 else ''}). Remove it from those "
                "operations first, or set the machine to 'inactive' instead."
            )
        try:
            with transaction(self.path) as conn:
                cur = conn.execute("DELETE FROM machines WHERE machine_id = ?", (machine_id,))
                if cur.rowcount == 0:
                    raise IntegrityConflictError(f"Machine '{machine_id}' does not exist.")
        except sqlite3.IntegrityError as exc:
            raise IntegrityConflictError(f"Machine {machine_id} is still referenced: {exc}") from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Machine could not be deleted: {exc}") from exc

    # ------------------------------------------------------------------ operations
    def list_operations(self) -> list[OperationRecord]:
        rows = self._read("SELECT * FROM operations ORDER BY order_id, sequence, operation_id")
        eligible: dict[str, list[EligibleMachine]] = {}
        for r in self._read(
            "SELECT operation_id, machine_id, duration_override FROM operation_machines ORDER BY machine_id"
        ):
            eligible.setdefault(r["operation_id"], []).append(
                EligibleMachine(machine_id=r["machine_id"], duration_override=r["duration_override"])
            )
        preds: dict[str, list[str]] = {}
        for r in self._read(
            "SELECT operation_id, predecessor_id FROM operation_dependencies ORDER BY predecessor_id"
        ):
            preds.setdefault(r["operation_id"], []).append(r["predecessor_id"])
        return [
            OperationRecord(
                operation_id=r["operation_id"],
                order_id=r["order_id"],
                operation_name=r["operation_name"],
                sequence=r["sequence"],
                processing_duration=r["processing_duration"],
                duration_is_estimate=bool(r["duration_is_estimate"]),
                duration_source=r["duration_source"],
                eligible_machines=eligible.get(r["operation_id"], []),
                predecessors=preds.get(r["operation_id"], []),
                changeover_category=r["changeover_category"],
                status=r["status"],
                notes=r["notes"],
                is_synthetic=bool(r["is_synthetic"]),
            )
            for r in rows
        ]

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        return next((o for o in self.list_operations() if o.operation_id == operation_id), None)

    def _write_operation_children(self, conn: sqlite3.Connection, op: OperationRecord) -> None:
        conn.execute("DELETE FROM operation_machines WHERE operation_id = ?", (op.operation_id,))
        conn.execute("DELETE FROM operation_dependencies WHERE operation_id = ?", (op.operation_id,))
        conn.executemany(
            "INSERT INTO operation_machines (operation_id, machine_id, duration_override) VALUES (?,?,?)",
            [(op.operation_id, em.machine_id, em.duration_override) for em in op.eligible_machines],
        )
        conn.executemany(
            "INSERT INTO operation_dependencies (operation_id, predecessor_id) VALUES (?, ?)",
            [(op.operation_id, p) for p in op.predecessors],
        )

    def insert_operation(self, op: OperationRecord) -> None:
        try:
            with transaction(self.path) as conn:
                conn.execute(
                    "INSERT INTO operations (operation_id, order_id, operation_name, sequence,"
                    " processing_duration, duration_is_estimate, duration_source, changeover_category,"
                    " status, notes, is_synthetic, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        op.operation_id,
                        op.order_id,
                        op.operation_name,
                        op.sequence,
                        op.processing_duration,
                        int(op.duration_is_estimate),
                        op.duration_source,
                        op.changeover_category,
                        op.status.value,
                        op.notes,
                        int(op.is_synthetic),
                        _now(),
                    ),
                )
                self._write_operation_children(conn, op)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc) or "PRIMARY" in str(exc):
                raise IntegrityConflictError(f"Operation ID '{op.operation_id}' already exists.") from exc
            raise IntegrityConflictError(
                f"Operation {op.operation_id} references a missing order, machine or predecessor ({exc})."
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Operation could not be saved: {exc}") from exc

    def update_operation(self, op: OperationRecord) -> None:
        try:
            with transaction(self.path) as conn:
                cur = conn.execute(
                    "UPDATE operations SET order_id=?, operation_name=?, sequence=?,"
                    " processing_duration=?, duration_is_estimate=?, duration_source=?,"
                    " changeover_category=?, status=?, notes=?, is_synthetic=?, updated_at=?"
                    " WHERE operation_id=?",
                    (
                        op.order_id,
                        op.operation_name,
                        op.sequence,
                        op.processing_duration,
                        int(op.duration_is_estimate),
                        op.duration_source,
                        op.changeover_category,
                        op.status.value,
                        op.notes,
                        int(op.is_synthetic),
                        _now(),
                        op.operation_id,
                    ),
                )
                if cur.rowcount == 0:
                    raise IntegrityConflictError(f"Operation '{op.operation_id}' does not exist.")
                self._write_operation_children(conn, op)
        except sqlite3.IntegrityError as exc:
            raise IntegrityConflictError(
                f"Operation {op.operation_id} references a missing order, machine or predecessor ({exc})."
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Operation could not be saved: {exc}") from exc

    def successors_of(self, operation_id: str) -> list[str]:
        return [
            r["operation_id"]
            for r in self._read(
                "SELECT operation_id FROM operation_dependencies WHERE predecessor_id = ?"
                " ORDER BY operation_id",
                (operation_id,),
            )
        ]

    def delete_operation(self, operation_id: str) -> None:
        succ = self.successors_of(operation_id)
        if succ:
            raise IntegrityConflictError(
                f"Operation {operation_id} is a predecessor of {', '.join(succ)}. Remove those "
                "dependencies first so no orphaned predecessor references remain."
            )
        try:
            with transaction(self.path) as conn:
                cur = conn.execute("DELETE FROM operations WHERE operation_id = ?", (operation_id,))
                if cur.rowcount == 0:
                    raise IntegrityConflictError(f"Operation '{operation_id}' does not exist.")
        except sqlite3.Error as exc:
            raise PersistenceError(f"Operation could not be deleted: {exc}") from exc

    # ------------------------------------------------------------------ changeovers
    def list_changeover_rules(self) -> list[ChangeoverRule]:
        return [
            ChangeoverRule(
                from_category=r["from_category"], to_category=r["to_category"], minutes=r["minutes"]
            )
            for r in self._read("SELECT * FROM changeover_rules ORDER BY from_category, to_category")
        ]

    def replace_changeover_rules(self, rules: list[ChangeoverRule]) -> None:
        try:
            with transaction(self.path) as conn:
                conn.execute("DELETE FROM changeover_rules")
                conn.executemany(
                    "INSERT INTO changeover_rules (from_category, to_category, minutes) VALUES (?,?,?)",
                    [(r.from_category, r.to_category, r.minutes) for r in rules],
                )
        except sqlite3.IntegrityError as exc:
            raise IntegrityConflictError(f"Duplicate changeover rule ({exc}).") from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Changeover rules could not be saved: {exc}") from exc

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> PlanningSettings:
        rows = self._read("SELECT value FROM settings WHERE key = 'planning'")
        if not rows:
            return PlanningSettings()
        return PlanningSettings.model_validate_json(rows[0]["value"])

    def save_settings(self, settings: PlanningSettings) -> None:
        try:
            with transaction(self.path) as conn:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('planning', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (settings.model_dump_json(),),
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Settings could not be saved: {exc}") from exc

    # ------------------------------------------------------------------ counts
    def counts(self) -> dict[str, int]:
        out = {}
        for key, table in (
            ("orders", "orders"),
            ("machines", "machines"),
            ("operations", "operations"),
            ("runs", "schedule_runs"),
        ):
            out[key] = self._read(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]  # noqa: S608 - fixed names
        return out

    # ------------------------------------------------------------------ schedule runs
    def insert_run(self, run: StoredRun) -> int:
        """Persist a run and its assignments atomically; returns the new run id.

        If anything fails the whole transaction is rolled back, so no half-saved run can
        appear as a validated schedule (testing_requirements 11.3).
        """
        if run.outcome not in OUTCOMES:
            raise PersistenceError(f"Unknown run outcome '{run.outcome}'.")
        try:
            with transaction(self.path) as conn:
                cur = conn.execute(
                    "INSERT INTO schedule_runs (created_at, outcome, solver_status, accepted, objective,"
                    " objective_value, best_bound, time_limit, workers, random_seed, runtime_seconds,"
                    " stopped_at_limit, solver_version, model_version, app_version, input_fingerprint,"
                    " snapshot_json, validation_json, metrics_json, model_stats_json, detail,"
                    " is_synthetic_data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run.created_at or _now(),
                        run.outcome,
                        run.solver_status,
                        int(run.accepted),
                        run.objective,
                        run.objective_value,
                        run.best_bound,
                        run.time_limit,
                        run.workers,
                        run.random_seed,
                        run.runtime_seconds,
                        int(run.stopped_at_limit),
                        run.solver_version,
                        run.model_version,
                        run.app_version,
                        run.input_fingerprint,
                        run.snapshot.canonical_json(),
                        json.dumps([i.to_dict() for i in run.validation_issues]),
                        json.dumps(run.metrics) if run.metrics is not None else None,
                        json.dumps(run.model_stats),
                        run.detail,
                        int(run.is_synthetic_data),
                    ),
                )
                run_id = int(cur.lastrowid)
                conn.executemany(
                    "INSERT INTO schedule_assignments (run_id, operation_id, order_id, machine_id,"
                    " start_time, end_time, duration) VALUES (?,?,?,?,?,?,?)",
                    [
                        (run_id, a.operation_id, a.order_id, a.machine_id, a.start, a.end, a.duration)
                        for a in run.assignments
                    ],
                )
                return run_id
        except sqlite3.Error as exc:
            raise PersistenceError(f"The scheduling run could not be saved: {exc}") from exc

    def _run(self, r: sqlite3.Row, assignments: list[ScheduledOperation]) -> StoredRun:
        return StoredRun(
            run_id=r["run_id"],
            created_at=r["created_at"],
            outcome=r["outcome"],
            solver_status=r["solver_status"],
            accepted=bool(r["accepted"]),
            objective=r["objective"],
            objective_value=r["objective_value"],
            best_bound=r["best_bound"],
            time_limit=r["time_limit"],
            workers=r["workers"],
            random_seed=r["random_seed"],
            runtime_seconds=r["runtime_seconds"],
            stopped_at_limit=bool(r["stopped_at_limit"]),
            solver_version=r["solver_version"],
            model_version=r["model_version"],
            app_version=r["app_version"],
            input_fingerprint=r["input_fingerprint"],
            snapshot=ProblemSnapshot.from_dict(json.loads(r["snapshot_json"])),
            assignments=assignments,
            validation_issues=[Issue.from_dict(d) for d in json.loads(r["validation_json"])],
            metrics=json.loads(r["metrics_json"]) if r["metrics_json"] else None,
            model_stats=json.loads(r["model_stats_json"]),
            detail=r["detail"],
            is_synthetic_data=bool(r["is_synthetic_data"]),
        )

    def _assignments(self, run_id: int) -> list[ScheduledOperation]:
        return [
            ScheduledOperation(
                r["operation_id"],
                r["order_id"],
                r["machine_id"],
                r["start_time"],
                r["end_time"],
                r["duration"],
            )
            for r in self._read(
                "SELECT * FROM schedule_assignments WHERE run_id = ? ORDER BY start_time, operation_id",
                (run_id,),
            )
        ]

    def get_run(self, run_id: int) -> StoredRun | None:
        rows = self._read("SELECT * FROM schedule_runs WHERE run_id = ?", (run_id,))
        return self._run(rows[0], self._assignments(run_id)) if rows else None

    def latest_accepted_run(self) -> StoredRun | None:
        rows = self._read("SELECT * FROM schedule_runs WHERE accepted = 1 ORDER BY run_id DESC LIMIT 1")
        return self._run(rows[0], self._assignments(rows[0]["run_id"])) if rows else None

    def latest_run(self) -> StoredRun | None:
        rows = self._read("SELECT * FROM schedule_runs ORDER BY run_id DESC LIMIT 1")
        return self._run(rows[0], self._assignments(rows[0]["run_id"])) if rows else None

    def list_runs(self, limit: int = 200) -> list[StoredRun]:
        """Run headers (without assignments) newest first."""
        return [
            self._run(r, [])
            for r in self._read("SELECT * FROM schedule_runs ORDER BY run_id DESC LIMIT ?", (limit,))
        ]
