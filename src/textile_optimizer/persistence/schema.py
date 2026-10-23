"""SQLite schema (version 1).

Design notes
* Foreign keys are enforced (``PRAGMA foreign_keys=ON`` on every connection).
* Orders -> operations -> dependencies/eligibility cascade on order deletion; a machine that is
  referenced by an operation cannot be deleted (RESTRICT), so assignments are never orphaned.
* ``schedule_runs`` keeps the *input snapshot as JSON* and ``schedule_assignments`` references
  only the run: historical results stay interpretable after the live data changes
  (technical_specification 11.3).
* Schema changes must bump SCHEMA_VERSION and add a migration step in ``db.migrate``.
"""

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    order_id      TEXT PRIMARY KEY,
    product_code  TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    quantity      REAL NOT NULL CHECK (quantity > 0),
    quantity_unit TEXT NOT NULL,
    release_time  INTEGER NOT NULL CHECK (release_time >= 0),
    due_time      INTEGER NOT NULL CHECK (due_time >= release_time),
    priority      INTEGER CHECK (priority IS NULL OR priority BETWEEN 1 AND 5),
    weight        INTEGER CHECK (weight IS NULL OR weight >= 0),
    status        TEXT NOT NULL CHECK (status IN ('draft','ready','archived')),
    notes         TEXT NOT NULL DEFAULT '',
    is_synthetic  INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
    machine_id   TEXT PRIMARY KEY,
    machine_name TEXT NOT NULL,
    machine_type TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('active','inactive')),
    notes        TEXT NOT NULL DEFAULT '',
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machine_capabilities (
    machine_id TEXT NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    process    TEXT NOT NULL,
    PRIMARY KEY (machine_id, process)
);

CREATE TABLE IF NOT EXISTS machine_intervals (
    interval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id  TEXT NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('available','downtime')),
    start_time  INTEGER NOT NULL CHECK (start_time >= 0),
    end_time    INTEGER NOT NULL,
    CHECK (end_time > start_time)
);

CREATE TABLE IF NOT EXISTS operations (
    operation_id        TEXT PRIMARY KEY,
    order_id            TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    operation_name      TEXT NOT NULL,
    sequence            INTEGER NOT NULL DEFAULT 1 CHECK (sequence >= 0),
    processing_duration INTEGER NOT NULL CHECK (processing_duration > 0),
    duration_is_estimate INTEGER NOT NULL DEFAULT 1,
    duration_source     TEXT NOT NULL DEFAULT '',
    changeover_category TEXT,
    status              TEXT NOT NULL CHECK (status IN ('active','archived')),
    notes               TEXT NOT NULL DEFAULT '',
    is_synthetic        INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_machines (
    operation_id      TEXT NOT NULL REFERENCES operations(operation_id) ON DELETE CASCADE,
    machine_id        TEXT NOT NULL REFERENCES machines(machine_id) ON DELETE RESTRICT,
    duration_override INTEGER CHECK (duration_override IS NULL OR duration_override > 0),
    PRIMARY KEY (operation_id, machine_id)
);

CREATE TABLE IF NOT EXISTS operation_dependencies (
    operation_id   TEXT NOT NULL REFERENCES operations(operation_id) ON DELETE CASCADE,
    predecessor_id TEXT NOT NULL REFERENCES operations(operation_id) ON DELETE CASCADE,
    PRIMARY KEY (operation_id, predecessor_id),
    CHECK (operation_id <> predecessor_id)
);

CREATE TABLE IF NOT EXISTS changeover_rules (
    from_category TEXT NOT NULL,
    to_category   TEXT NOT NULL,
    minutes       INTEGER NOT NULL CHECK (minutes >= 0),
    PRIMARY KEY (from_category, to_category)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_runs (
    run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN
        ('ACCEPTED','INFEASIBLE','NO_SOLUTION','MODEL_INVALID','VALIDATION_FAILED','ERROR')),
    solver_status     TEXT,
    accepted          INTEGER NOT NULL CHECK (accepted IN (0,1)),
    objective         TEXT NOT NULL,
    objective_value   REAL,
    best_bound        REAL,
    time_limit        REAL NOT NULL,
    workers           INTEGER NOT NULL,
    random_seed       INTEGER NOT NULL,
    runtime_seconds   REAL,
    stopped_at_limit  INTEGER NOT NULL DEFAULT 0,
    solver_version    TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    app_version       TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    snapshot_json     TEXT NOT NULL,
    validation_json   TEXT NOT NULL DEFAULT '[]',
    metrics_json      TEXT,
    model_stats_json  TEXT NOT NULL DEFAULT '{}',
    detail            TEXT NOT NULL DEFAULT '',
    is_synthetic_data INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schedule_assignments (
    run_id       INTEGER NOT NULL REFERENCES schedule_runs(run_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    order_id     TEXT NOT NULL,
    machine_id   TEXT NOT NULL,
    start_time   INTEGER NOT NULL,
    end_time     INTEGER NOT NULL,
    duration     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operations_order ON operations(order_id);
CREATE INDEX IF NOT EXISTS idx_assign_run ON schedule_assignments(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_accepted ON schedule_runs(accepted, run_id);
"""
