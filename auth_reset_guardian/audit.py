from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import AccountObservation, ResetCredit, utc_iso


SCHEMA_VERSION = 1


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class RedemptionAttempt:
    attempt_id: str
    idempotency_key: str
    resumed: bool


class AuditStore:
    """SQLite audit log. No provider IDs, OAuth material, or broker IDs enter this store."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        self._connection = sqlite3.connect(self.path, timeout=30.0)
        os.chmod(self.path, 0o600)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "AuditStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _initialize(self) -> None:
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in {0, SCHEMA_VERSION}:
            raise RuntimeError(f"unsupported reset guardian audit schema version: {version}")
        self._connection.executescript(
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
            CREATE INDEX IF NOT EXISTS snapshots_account_idx ON snapshots(account_ref, captured_at);

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
                PRIMARY KEY(mode, credit_ref, expires_at, threshold_hours)
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
                ON redemption_attempts(credit_ref, expires_at, status, updated_at);

            CREATE TABLE IF NOT EXISTS notifications (
                notification_key TEXT PRIMARY KEY,
                first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                first_seen_at TEXT NOT NULL,
                last_attempt_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                last_error_code TEXT
            );
            """
        )
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.commit()

    def start_run(self, *, mode: str, now: datetime) -> str:
        run_id = uuid4().hex
        with self._connection:
            self._connection.execute(
                "INSERT INTO runs(run_id, mode, started_at, status) VALUES (?, ?, ?, 'running')",
                (run_id, mode, utc_iso(now)),
            )
        return run_id

    def finish_run(
        self,
        *,
        run_id: str,
        now: datetime,
        status: str,
        summary: dict[str, Any],
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE runs
                   SET completed_at = ?, status = ?, account_count = ?, credit_count = ?,
                       warning_count = ?, redemption_count = ?, error_count = ?, summary_json = ?
                 WHERE run_id = ?
                """,
                (
                    utc_iso(now),
                    status,
                    int(summary.get("account_count", 0)),
                    int(summary.get("credit_count", 0)),
                    int(summary.get("warning_count", 0)),
                    int(summary.get("redemption_count", 0)),
                    int(summary.get("error_count", 0)),
                    _json(summary),
                    run_id,
                ),
            )

    def record_snapshot(self, *, run_id: str, phase: str, observation: AccountObservation) -> None:
        sanitized = observation.sanitized()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO snapshots(run_id, captured_at, phase, account_ref, account_label, state_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_iso(observation.captured_at),
                    phase,
                    observation.descriptor.account_ref,
                    observation.descriptor.label,
                    _json(sanitized),
                ),
            )

    def record_event(
        self,
        *,
        run_id: str,
        now: datetime,
        event_type: str,
        severity: str = "info",
        account_ref: str | None = None,
        account_label: str | None = None,
        credit_ref: str | None = None,
        expires_at: datetime | None = None,
        threshold_hours: int | None = None,
        attempt_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO events(
                    run_id, occurred_at, event_type, severity, account_ref, account_label,
                    credit_ref, expires_at, threshold_hours, attempt_id, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_iso(now),
                    event_type,
                    severity,
                    account_ref,
                    account_label,
                    credit_ref,
                    utc_iso(expires_at) if expires_at else None,
                    threshold_hours,
                    attempt_id,
                    _json(details or {}),
                ),
            )

    def claim_warning(
        self,
        *,
        run_id: str,
        mode: str,
        now: datetime,
        account_ref: str,
        credit: ResetCredit,
        threshold_hours: int,
    ) -> bool:
        assert credit.expires_at is not None
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO warning_marks(
                    mode, account_ref, credit_ref, expires_at, threshold_hours,
                    first_run_id, first_observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mode,
                    account_ref,
                    credit.credit_ref,
                    utc_iso(credit.expires_at),
                    threshold_hours,
                    run_id,
                    utc_iso(now),
                ),
            )
        return cursor.rowcount == 1

    def start_or_resume_attempt(
        self,
        *,
        run_id: str,
        now: datetime,
        observation: AccountObservation,
        credit: ResetCredit,
        reason: str,
    ) -> RedemptionAttempt:
        assert credit.expires_at is not None
        row = self._connection.execute(
            """
            SELECT attempt_id, idempotency_key
              FROM redemption_attempts
             WHERE credit_ref = ? AND expires_at = ? AND status IN ('started', 'uncertain')
             ORDER BY started_at ASC LIMIT 1
            """,
            (credit.credit_ref, utc_iso(credit.expires_at)),
        ).fetchone()
        if row is not None:
            with self._connection:
                self._connection.execute(
                    "UPDATE redemption_attempts SET run_id = ?, updated_at = ? WHERE attempt_id = ?",
                    (run_id, utc_iso(now), row["attempt_id"]),
                )
            return RedemptionAttempt(
                attempt_id=str(row["attempt_id"]),
                idempotency_key=str(row["idempotency_key"]),
                resumed=True,
            )

        attempt_id = uuid4().hex
        idempotency_key = f"pitchai-reset-guardian:{credit.credit_ref[:20]}:{attempt_id}"
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO redemption_attempts(
                    attempt_id, idempotency_key, run_id, account_ref, account_label,
                    credit_ref, expires_at, reason, started_at, updated_at, status, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'started', '{}')
                """,
                (
                    attempt_id,
                    idempotency_key,
                    run_id,
                    observation.descriptor.account_ref,
                    observation.descriptor.label,
                    credit.credit_ref,
                    utc_iso(credit.expires_at),
                    reason,
                    utc_iso(now),
                    utc_iso(now),
                ),
            )
        return RedemptionAttempt(attempt_id=attempt_id, idempotency_key=idempotency_key, resumed=False)

    def update_attempt(
        self,
        *,
        attempt_id: str,
        now: datetime,
        status: str,
        outcome: str | None = None,
        windows_reset: int | None = None,
        verification: str | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE redemption_attempts
                   SET updated_at = ?, status = ?, outcome = ?, windows_reset = ?,
                       verification = ?, error_code = ?, details_json = ?
                 WHERE attempt_id = ?
                """,
                (
                    utc_iso(now),
                    status,
                    outcome,
                    windows_reset,
                    verification,
                    error_code,
                    _json(details or {}),
                    attempt_id,
                ),
            )

    def pending_attempts_for_account(self, *, account_ref: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT attempt_id, credit_ref, expires_at, status, outcome, windows_reset
              FROM redemption_attempts
             WHERE account_ref = ? AND status IN ('started', 'uncertain', 'verification_failed')
             ORDER BY started_at ASC
            """,
            (account_ref,),
        ).fetchall()
        return [dict(row) for row in rows]

    def notification_due(self, *, notification_key: str, run_id: str, now: datetime) -> bool:
        row = self._connection.execute(
            "SELECT status FROM notifications WHERE notification_key = ?", (notification_key,)
        ).fetchone()
        if row is not None:
            return str(row["status"]) != "sent"
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO notifications(notification_key, first_run_id, first_seen_at, status)
                VALUES (?, ?, ?, 'pending')
                """,
                (notification_key, run_id, utc_iso(now)),
            )
        return True

    def record_notification_result(
        self,
        *,
        notification_keys: list[str],
        now: datetime,
        sent: bool,
        error_code: str | None,
    ) -> None:
        with self._connection:
            self._connection.executemany(
                """
                UPDATE notifications
                   SET last_attempt_at = ?, attempts = attempts + 1,
                       status = ?, last_error_code = ?
                 WHERE notification_key = ?
                """,
                [
                    (utc_iso(now), "sent" if sent else "failed", error_code, key)
                    for key in notification_keys
                ],
            )

    def latest_status(self) -> dict[str, Any]:
        run = self._connection.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        upcoming = self._connection.execute(
            """
            SELECT account_label, captured_at, state_json
              FROM snapshots
             WHERE snapshot_id IN (
                 SELECT MAX(snapshot_id) FROM snapshots GROUP BY account_ref
             )
             ORDER BY account_label
            """
        ).fetchall()
        attempts = self._connection.execute(
            """
            SELECT account_label, credit_ref, expires_at, started_at, updated_at,
                   status, outcome, windows_reset, verification, error_code
              FROM redemption_attempts ORDER BY started_at DESC LIMIT 20
            """
        ).fetchall()
        return {
            "latest_run": dict(run) if run else None,
            "latest_accounts": [
                {
                    "account_label": row["account_label"],
                    "captured_at": row["captured_at"],
                    "state": json.loads(row["state_json"]),
                }
                for row in upcoming
            ],
            "recent_redemption_attempts": [dict(row) for row in attempts],
        }

    def recent_events(self, *, limit: int) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM events ORDER BY event_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
