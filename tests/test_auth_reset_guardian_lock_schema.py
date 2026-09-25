# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian deployment, concurrency, and audit migration behavior."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from auth_reset_guardian.audit import SCHEMA_VERSION, AuditStore
from auth_reset_guardian.audit_types import select_connection
from auth_reset_guardian.cli import exclusive_lock
from domain_checks.testing import verify
from tests.auth_reset_guardian_sql_support import (
    required_row,
    row_int,
    row_text,
)

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_LOCK_WAIT_ELAPSED_SECONDS = 0.04


def _hold_audit_lock(db_path: Path) -> int:
    """Hold one nonblocking guardian audit lock for a collision test.

    Returns:
        The computed value.

    """
    lock_path = db_path.with_suffix(db_path.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


def _release_audit_lock(descriptor: int) -> None:
    """Release and close one test-owned audit lock descriptor."""
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _expect_lock_timeout(db_path: Path) -> None:
    """Require one held lock to fail after its bounded wait."""
    with pytest.raises(SystemExit, match="held the audit lock beyond"), exclusive_lock(db_path, wait_seconds=0.02):
        pass


def test_exclusive_lock_waits_for_a_colliding_run_instead_of_failing(
    tmp_path: Path,
) -> None:
    """Wait for a colliding guardian process instead of failing early."""
    db_path = tmp_path / "audit.sqlite3"
    descriptor = _hold_audit_lock(db_path)

    timer = threading.Timer(0.05, _release_audit_lock, args=(descriptor,))
    timer.start()
    started = time.monotonic()
    with exclusive_lock(db_path, wait_seconds=0.5):
        pass
    elapsed = time.monotonic() - started
    timer.join()

    verify(elapsed >= MINIMUM_LOCK_WAIT_ELAPSED_SECONDS)


def test_exclusive_lock_still_fails_loudly_after_wait_timeout(tmp_path: Path) -> None:
    """Fail loudly after the configured collision wait expires."""
    db_path = tmp_path / "audit.sqlite3"
    descriptor = _hold_audit_lock(db_path)
    try:
        _expect_lock_timeout(db_path)
    finally:
        _release_audit_lock(descriptor)


def test_deployment_live_dry_run_waits_for_quarter_hour_service() -> None:
    """Keep deployment dry runs tolerant of the scheduled service cadence."""
    script = (ROOT / "ops" / "deploy_auth_reset_guardian.sh").read_text()

    verify('readonly LOCK_WAIT_SECONDS="300"' in script)
    verify(
        ('--audit-db "${AUDIT_DB}" \\\n  --lock-wait-seconds "${LOCK_WAIT_SECONDS}" \\\n  run --dry-run --no-notify')
        in script,
    )


def test_deployment_script_handles_expected_absence_without_erasing_failures() -> None:
    """Distinguish expected deployment absence from real command failures."""
    script = (ROOT / "ops" / "deploy_auth_reset_guardian.sh").read_text()

    verify("|| true" not in script)
    verify(
        'if ! previous_target="$(readlink -f -- "${CURRENT_LINK}")" || [[ ! -d "${previous_target}" ]]; then' in script,
    )
    verify("if ! systemctl disable --now pitchai-auth-reset-guardian.timer" in script)
    verify("if ! journalctl -u pitchai-auth-reset-guardian.service" in script)
    verify("mandatory rollback continues" in script)


def test_schema_v1_migrates_warning_scope_without_losing_marks(tmp_path: Path) -> None:
    """Migrate durable warning scope without dropping existing marks."""
    db_path = tmp_path / "audit.sqlite3"
    with sqlite3.connect(db_path) as connection:
        _ = connection.executescript(
            """
            CREATE TABLE runs (
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
            CREATE TABLE warning_marks (
                mode TEXT NOT NULL,
                account_ref TEXT NOT NULL,
                credit_ref TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                threshold_hours INTEGER NOT NULL,
                first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                first_observed_at TEXT NOT NULL,
                PRIMARY KEY(mode, credit_ref, expires_at, threshold_hours)
            );
            INSERT INTO runs(run_id, mode, started_at, status)
            VALUES ('old-run', 'live', '2026-08-10T19:00:00Z', 'ok');
            INSERT INTO warning_marks(
                mode, account_ref, credit_ref, expires_at, threshold_hours,
                first_run_id, first_observed_at
            ) VALUES (
                'live', 'account-a', 'credit-a', '2026-08-11T21:08:33Z', 48,
                'old-run', '2026-08-10T19:00:00Z'
            );
            PRAGMA user_version = 1;
            """,
        )

    with AuditStore(db_path):
        pass

    with sqlite3.connect(db_path) as connection:
        user_version = required_row(
            select_connection(connection).execute("PRAGMA user_version"),
        )
        verify(row_int(user_version, 0) == SCHEMA_VERSION)
        table_info = (
            select_connection(connection)
            .execute(
                "PRAGMA table_info(warning_marks)",
            )
            .fetchall()
        )
        ordered_table_info = sorted(
            table_info,
            key=lambda item: row_int(item, 5),
        )
        primary_key_rows = (
            row for row in ordered_table_info if row_int(row, 5)
        )
        primary_key: list[str] = [
            row_text(row, 1) for row in primary_key_rows
        ]
        verify(
            primary_key
            == [
                "mode",
                "account_ref",
                "credit_ref",
                "expires_at",
                "threshold_hours",
            ],
        )
        retained_rows = (
            select_connection(connection)
            .execute(
                "SELECT mode, account_ref, credit_ref, expires_at, threshold_hours FROM warning_marks",
            )
            .fetchall()
        )
        retained: list[tuple[str, str, str, str, int]] = [
            (
                row_text(row, 0),
                row_text(row, 1),
                row_text(row, 2),
                row_text(row, 3),
                row_int(row, 4),
            )
            for row in retained_rows
        ]
        verify(
            retained
            == [
                ("live", "account-a", "credit-a", "2026-08-11T21:08:33Z", 48),
            ],
        )
        index_rows = (
            select_connection(connection)
            .execute(
                "PRAGMA index_info(redemption_open_idx)",
            )
            .fetchall()
        )
        index_columns: list[str] = [row_text(row, 2) for row in index_rows]
        verify(index_columns[:3] == ["account_ref", "credit_ref", "expires_at"])
