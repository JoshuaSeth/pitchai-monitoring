# Copyright (c) 2026 PitchAI. All rights reserved.
"""SQLite schema and value boundary for hotpath monitoring state."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

SCHEMA_VERSION = 1
type SqlValue = str | int | float | bytes | None


class HotpathStateError(RuntimeError):
    """Persisted hotpath state violates the expected schema contract."""


def connect(path: str) -> sqlite3.Connection:
    """Open the single-host registry database with bounded writer waits.

    Returns:
        A configured SQLite connection.

    Raises:
        ValueError: If no database path was provided.
    """
    selected = path.strip()
    if not selected:
        error = "hotpath database path is required"
        raise ValueError(error)
    Path(selected).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(selected, timeout=30, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    _ = connection.execute("PRAGMA foreign_keys = ON")
    _ = connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def ensure_schema(path: str) -> None:
    """Create the additive hotpath schema without changing registry tables.

    Raises:
        HotpathStateError: If a future incompatible schema is present.
    """
    with closing(connect(path)) as connection:
        _ = connection.execute(
            "CREATE TABLE IF NOT EXISTS hotpath_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        )
        row = cast(
            "sqlite3.Row | None",
            connection.execute(
                "SELECT value FROM hotpath_schema_meta WHERE key = 'version'",
            ).fetchone(),
        )
        current = int(row_string(row, "value")) if row is not None else 0
        if current not in {0, SCHEMA_VERSION}:
            error = f"unsupported hotpath schema version {current}"
            raise HotpathStateError(error)
        _create_v1(connection)
        _ = connection.execute(
            "INSERT OR REPLACE INTO hotpath_schema_meta (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )


def row_value(row: sqlite3.Row, key: str) -> SqlValue:
    """Narrow SQLite's untyped row value to its documented value union.

    Returns:
        The raw SQLite scalar.
    """
    return cast("SqlValue", row[key])


def row_string(row: sqlite3.Row, key: str) -> str:
    """Read one required text field.

    Returns:
        The stored string.

    Raises:
        HotpathStateError: If the field is not text.
    """
    value = row_value(row, key)
    if not isinstance(value, str):
        error = f"stored {key} must be text"
        raise HotpathStateError(error)
    return value


def row_optional_string(row: sqlite3.Row, key: str) -> str | None:
    """Read one nullable text field.

    Returns:
        The stored string or ``None``.

    Raises:
        HotpathStateError: If a non-null field is not text.
    """
    value = row_value(row, key)
    if value is not None and not isinstance(value, str):
        error = f"stored {key} must be nullable text"
        raise HotpathStateError(error)
    return value


def row_float(row: sqlite3.Row, key: str) -> float:
    """Read one required numeric field.

    Returns:
        The stored value as a float.

    Raises:
        HotpathStateError: If the field is not numeric.
    """
    value = row_value(row, key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        error = f"stored {key} must be numeric"
        raise HotpathStateError(error)
    return float(value)


def row_integer(row: sqlite3.Row, key: str) -> int:
    """Read one required integer field.

    Returns:
        The stored integer.

    Raises:
        HotpathStateError: If the field is not an integer.
    """
    value = row_value(row, key)
    if not isinstance(value, int) or isinstance(value, bool):
        error = f"stored {key} must be an integer"
        raise HotpathStateError(error)
    return value


def _create_v1(connection: sqlite3.Connection) -> None:
    _ = connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS hotpath_reports (
          report_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
          lane_id TEXT NOT NULL, project TEXT NOT NULL, name TEXT NOT NULL,
          target_surface TEXT NOT NULL, occurred_at_ts REAL NOT NULL,
          received_at_ts REAL NOT NULL, source_sha TEXT NOT NULL, deployed_sha TEXT,
          success INTEGER NOT NULL, severity TEXT NOT NULL, failure_reason TEXT,
          failure_class TEXT, failure_phase TEXT, evidence_uri TEXT NOT NULL,
          duration_seconds REAL NOT NULL, artifact_receipt_sha256 TEXT NOT NULL,
          run_id TEXT NOT NULL, synthetic INTEGER NOT NULL, synthetic_scenario TEXT,
          exercise_event_bus INTEGER NOT NULL, incident_fingerprint TEXT,
          event_action TEXT NOT NULL, canonical_json TEXT NOT NULL,
          receipt_json TEXT NOT NULL, report_receipt_sha256 TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hotpath_reports_lane_time
          ON hotpath_reports(lane_id, occurred_at_ts DESC);
        CREATE INDEX IF NOT EXISTS hotpath_reports_received
          ON hotpath_reports(received_at_ts DESC);
        CREATE TABLE IF NOT EXISTS hotpath_lane_state (
          lane_id TEXT PRIMARY KEY,
          latest_report_id TEXT NOT NULL REFERENCES hotpath_reports(report_id),
          latest_occurred_at_ts REAL NOT NULL, current_success INTEGER NOT NULL,
          current_severity TEXT NOT NULL, current_fingerprint TEXT,
          fail_streak INTEGER NOT NULL, success_streak INTEGER NOT NULL,
          last_event_fingerprint TEXT, last_event_at_ts REAL
        );
        CREATE TABLE IF NOT EXISTS hotpath_event_outbox (
          intent_id TEXT PRIMARY KEY,
          report_id TEXT NOT NULL REFERENCES hotpath_reports(report_id),
          event_kind TEXT NOT NULL, occurred_at_ts REAL NOT NULL,
          details_json TEXT NOT NULL, delivery_entry_json TEXT, status TEXT NOT NULL,
          receiver_event_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at_ts REAL NOT NULL DEFAULT 0, last_error TEXT,
          created_at_ts REAL NOT NULL, updated_at_ts REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hotpath_outbox_due
          ON hotpath_event_outbox(status, next_attempt_at_ts, created_at_ts);
        """,
    )
