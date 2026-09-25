# Copyright (c) 2026 PitchAI. All rights reserved.
"""Own the guardian audit connection and schema lifecycle."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Self

from .audit_types import AuditDataError, select_connection

if TYPE_CHECKING:
    from types import TracebackType

SCHEMA_VERSION = 2


class AuditConnection:
    """Maintain the private SQLite connection used by guardian audit domains."""

    def __init__(self, path: Path):
        """Open and initialize a permission-restricted audit database."""
        self.path: Path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        Path(self.path.parent).chmod(0o700)
        self._connection: sqlite3.Connection = sqlite3.connect(self.path, timeout=30.0)
        Path(self.path).chmod(0o600)
        self._connection.row_factory = sqlite3.Row
        _ = self._connection.execute("PRAGMA foreign_keys = ON")
        _ = self._connection.execute("PRAGMA journal_mode = WAL")
        _ = self._connection.execute("PRAGMA synchronous = FULL")
        _ = self._connection.execute("PRAGMA busy_timeout = 30000")
        self._initialize()

    def close(self) -> None:
        """Close the audit database connection."""
        self._connection.close()

    def __enter__(self) -> Self:
        """Enter this managed audit connection.

        Returns:
            The resulting value.

        """
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the audit connection when its context exits."""
        del exception_type, exception, traceback
        self._connection.close()

    def _initialize(self) -> None:
        version_row = (
            select_connection(self._connection)
            .execute(
                "PRAGMA user_version",
            )
            .fetchone()
        )
        if version_row is None:
            msg = "SQLite did not return its audit schema version"
            raise AuditDataError(msg)
        version_value = version_row[0]
        if not isinstance(version_value, int):
            msg = "SQLite returned a non-integer audit schema version"
            raise AuditDataError(msg)
        version = version_value
        if version not in {0, 1, SCHEMA_VERSION}:
            msg = f"unsupported reset guardian audit schema version: {version}"
            raise RuntimeError(msg)
        _ = self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                account_count INTEGER NOT NULL DEFAULT 0,
                credit_count INTEGER NOT NULL DEFAULT 0,
                warning_count INTEGER NOT NULL DEFAULT 0,
                redemption_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                captured_at TEXT NOT NULL,
                phase TEXT NOT NULL,
                account_ref TEXT NOT NULL,
                account_label TEXT NOT NULL,
                state_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS snapshots_run_idx ON snapshots(run_id, snapshot_id);
            CREATE INDEX IF NOT EXISTS snapshots_account_idx
                ON snapshots(account_ref, captured_at);

            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                account_ref TEXT,
                account_label TEXT,
                credit_ref TEXT,
                expires_at TEXT,
                threshold_hours INTEGER,
                attempt_id TEXT,
                details_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_run_idx ON events(run_id, event_id);
            CREATE INDEX IF NOT EXISTS events_credit_idx ON events(credit_ref, occurred_at);

            CREATE TABLE IF NOT EXISTS warning_marks (
                mode TEXT NOT NULL,
                account_ref TEXT NOT NULL,
                credit_ref TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                threshold_hours INTEGER NOT NULL,
                first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                first_observed_at TEXT NOT NULL,
                PRIMARY KEY(mode, account_ref, credit_ref, expires_at, threshold_hours)
            );

            CREATE TABLE IF NOT EXISTS redemption_attempts (
                attempt_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                account_ref TEXT NOT NULL,
                account_label TEXT NOT NULL,
                credit_ref TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                outcome TEXT,
                windows_reset INTEGER,
                verification TEXT,
                error_code TEXT,
                details_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS redemption_open_idx
                ON redemption_attempts(account_ref, credit_ref, expires_at, status, updated_at);

            CREATE TABLE IF NOT EXISTS notifications (
                notification_key TEXT PRIMARY KEY,
                first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                first_seen_at TEXT NOT NULL,
                last_attempt_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                last_error_code TEXT
            );
            """,
        )
        if version == 1:
            _ = self._connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE warning_marks_v2 (
                    mode TEXT NOT NULL,
                    account_ref TEXT NOT NULL,
                    credit_ref TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    threshold_hours INTEGER NOT NULL,
                    first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                    first_observed_at TEXT NOT NULL,
                    PRIMARY KEY(mode, account_ref, credit_ref, expires_at, threshold_hours)
                );
                INSERT INTO warning_marks_v2(
                    mode, account_ref, credit_ref, expires_at, threshold_hours,
                    first_run_id, first_observed_at
                )
                SELECT mode, account_ref, credit_ref, expires_at, threshold_hours,
                       first_run_id, first_observed_at
                  FROM warning_marks;
                DROP TABLE warning_marks;
                ALTER TABLE warning_marks_v2 RENAME TO warning_marks;
                DROP INDEX IF EXISTS redemption_open_idx;
                CREATE INDEX redemption_open_idx
                    ON redemption_attempts(
                        account_ref, credit_ref, expires_at, status, updated_at
                    );
                COMMIT;
                """,
            )
        _ = self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.commit()
