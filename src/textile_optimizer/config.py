"""Application configuration: paths, defaults and validated limits.

Paths can be overridden with environment variables so tests (and users) can use
isolated databases:

* ``TPO_DATA_DIR`` - directory for the database, logs and backups.
* ``TPO_DB_PATH``  - full path of the SQLite file (overrides the default inside the data dir).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Quantity units accepted for production orders. Units are never converted or combined
# (project_explanation 6.1). Extend this tuple deliberately if another unit is needed.
QUANTITY_UNITS: tuple[str, ...] = ("kg", "pieces", "metres", "rolls")

# Planning defaults. They are *defaults for a new database only*: the planner must set the
# real planning origin and horizon (textile_scheduling_rules 11.1).
DEFAULT_ORIGIN = datetime(2026, 1, 5, 8, 0)  # Monday 08:00 - sample default, not a factory fact
DEFAULT_HORIZON_END_MINUTES = 7 * 24 * 60
DEFAULT_TIME_LIMIT_SECONDS = 30.0
MIN_TIME_LIMIT_SECONDS = 0.1
MAX_TIME_LIMIT_SECONDS = 3600.0
DEFAULT_WORKERS = 1  # single worker favours reproducibility (technical_specification 9.4)
MAX_WORKERS = 16
DEFAULT_SEED = 1
MAX_HORIZON_MINUTES = 10 * 365 * 24 * 60  # keeps CP-SAT integer ranges small and safe

TIME_UNIT_LABEL = "minutes"


def data_dir() -> Path:
    """Return the data directory, creating it if necessary."""
    path = Path(os.environ.get("TPO_DATA_DIR", PROJECT_ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    """Return the SQLite database path (the file is created on first use)."""
    override = os.environ.get("TPO_DB_PATH")
    if override:
        path = Path(override)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return data_dir() / "textile_optimizer.db"


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path
