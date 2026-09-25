# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian recheck-error notification identity scope."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.audit_types import select_connection
from auth_reset_guardian.clients import SimulationSource
from auth_reset_guardian.guardian import Guardian
from auth_reset_guardian.models import utc_iso
from domain_checks.testing import verify
from tests.auth_reset_guardian_sql_support import row_text
from tests.auth_reset_guardian_support import (
    UTC,
    guardian_fixture,
    required_array,
    required_array_object,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from auth_reset_guardian.guardian import GuardianRunSummary

EXPECTED_RECHECK_FAILURE_COUNT = 2


def _run_recheck_failure(
    *,
    now: datetime,
    expiry: datetime,
    db_path: Path,
    notifier: Callable[[str], None],
) -> GuardianRunSummary:
    """Run one dry live scan whose fresh redemption recheck fails.

    Returns:
        The resulting value.

    """
    fixture = guardian_fixture(expires_at=expiry, credit_id="reused-provider-id")
    accounts = required_array(fixture, "accounts")
    account = required_array_object(accounts, 0)
    account["fail_on_refresh"] = 2
    source = SimulationSource(fixture, clock=lambda: now)
    with AuditStore(db_path) as audit:
        return Guardian(
            source=source,
            audit=audit,
            notifier=notifier,
            clock=lambda: now,
        ).run(mode="live", dry_run=True)


def _read_recheck_scope(db_path: Path) -> tuple[set[str], list[str]]:
    """Read persisted notification identities and event expiries.

    Returns:
        The resulting collection.

    """
    notification_query = (
        "SELECT notification_key FROM notifications "
        "WHERE notification_key LIKE 'recheck-error:%' ORDER BY notification_key"
    )
    expiry_query = "SELECT expires_at FROM events WHERE event_type = 'redemption_recheck_failed' ORDER BY expires_at"
    with sqlite3.connect(db_path) as connection:
        typed_connection = select_connection(connection)
        key_rows = typed_connection.execute(notification_query).fetchall()
        expiry_rows = typed_connection.execute(expiry_query).fetchall()
    notification_keys: set[str] = set()
    notification_keys.update(row_text(row, 0) for row in key_rows)
    event_expiries: list[str] = [row_text(row, 0) for row in expiry_rows]
    return notification_keys, event_expiries


def test_recheck_error_notification_is_scoped_by_expected_expiry(
    tmp_path: Path,
) -> None:
    """Scope recheck-failure notifications to the expected credit expiry."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    messages: list[str] = []

    def record_notification(message: str) -> None:
        messages.append(message)

    db_path = tmp_path / "audit.sqlite3"
    expiries = (now + timedelta(hours=1), now + timedelta(hours=1, minutes=15))
    for expiry in expiries:
        summary = _run_recheck_failure(
            now=now,
            expiry=expiry,
            db_path=db_path,
            notifier=record_notification,
        )
        verify(summary.redemption_attempt_count == 0)
        verify(summary.error_count == 1)

    verify(len(messages) == EXPECTED_RECHECK_FAILURE_COUNT)
    for message in messages:
        verify("fresh redemption recheck failed" in message)
    notification_keys, event_expiries = _read_recheck_scope(db_path)
    verify(len(notification_keys) == EXPECTED_RECHECK_FAILURE_COUNT)
    expected_expiries: list[str] = [utc_iso(expiry) for expiry in expiries]
    verify(event_expiries == sorted(expected_expiries))
