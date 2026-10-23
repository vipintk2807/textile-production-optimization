"""SQLite connection handling, schema initialisation and safe backup."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..errors import PersistenceError
from .schema import SCHEMA_SQL, SCHEMA_VERSION


def connect(path: Path | str) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(str(path), timeout=10)
    except sqlite3.Error as exc:
        raise PersistenceError(
            f"The database could not be opened ({exc}). Check the path and permissions."
        ) from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(path: Path | str) -> Iterator[sqlite3.Connection]:
    """One transaction: commit on success, roll back on *any* exception."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | str) -> None:
    """Create missing tables. Never drops or resets existing data."""
    try:
        with transaction(path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise PersistenceError(
                    f"The database was created by a newer version (schema {version}); "
                    f"this application supports schema {SCHEMA_VERSION}."
                )
            conn.executescript(SCHEMA_SQL)
            migrate(conn, version)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    except sqlite3.Error as exc:
        raise PersistenceError(f"The database could not be initialised: {exc}") from exc


def migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Placeholder for future schema migrations (version 1 is the first release)."""
    # Add `if from_version < 2: ...` blocks here when SCHEMA_VERSION is increased.
    return None


def backup_database(source: Path | str, destination: Path | str) -> Path:
    """Copy the database using SQLite's online backup API (safe while the app is running)."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise PersistenceError(f"Backup target already exists and will not be overwritten: {destination}")
    src = connect(source)
    try:
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.Error as exc:
        destination.unlink(missing_ok=True)
        raise PersistenceError(f"Backup failed: {exc}") from exc
    finally:
        src.close()
    return destination
