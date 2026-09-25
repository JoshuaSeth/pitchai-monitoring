# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian warning persistence and notification retry behavior."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.clients import SimulationSource
from auth_reset_guardian.guardian import Guardian, NotificationError
from domain_checks.testing import verify
from tests.auth_reset_guardian_event_support import read_events
from tests.auth_reset_guardian_sql_support import count_rows
from tests.auth_reset_guardian_support import (
    UTC,
    MutableClock,
    guardian_fixture,
    required_array,
    required_array_object,
)
from tests.auth_test_contract import required_integer

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_RETRY_NOTIFICATION_COUNT = 2
EXPECTED_SCOPED_ACCOUNT_COUNT = 2
EXPECTED_SCOPED_WARNING_COUNT = 6


def test_warning_thresholds_are_emitted_once_per_mode_across_restarts(
    tmp_path: Path,
) -> None:
    """Persist each crossed warning threshold only once across restarts."""
    now = datetime(2026, 8, 10, 19, 0, tzinfo=UTC)
    clock = MutableClock(now)
    source = SimulationSource(
        guardian_fixture(expires_at=now + timedelta(hours=26)),
        clock=clock,
    )
    db_path = tmp_path / "audit.sqlite3"

    with AuditStore(db_path) as audit:
        first = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation",
            dry_run=False,
        )
    verify(first.warning_count == 1)
    verify(first.redemption_attempt_count == 0)

    with AuditStore(db_path) as audit:
        second = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation",
            dry_run=False,
        )
    verify(second.warning_count == 0)

    clock.advance(timedelta(hours=3))
    with AuditStore(db_path) as audit:
        third = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation",
            dry_run=False,
        )
    verify(third.warning_count == 1)
    thresholds: list[int] = []
    for event in read_events(db_path):
        if event.get("event_type") != "expiry_warning":
            continue
        thresholds.append(
            required_integer(
                event.get("threshold_hours"),
                label="warning threshold hours",
            ),
        )
    verify(thresholds == [48, 24])


def test_all_required_warning_thresholds_are_persisted_across_time(
    tmp_path: Path,
) -> None:
    """Persist every required threshold as simulated time approaches expiry."""
    initial = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    expiry = initial + timedelta(hours=49)
    clock = MutableClock(initial)
    source = SimulationSource(guardian_fixture(expires_at=expiry), clock=clock)
    db_path = tmp_path / "audit.sqlite3"

    for remaining_hours in (47, 23, 5, 1.5, 0.5):
        clock.now = expiry - timedelta(hours=remaining_hours)
        with AuditStore(db_path) as audit:
            summary = Guardian(source=source, audit=audit, clock=clock).run(
                mode="threshold_coverage",
                dry_run=True,
            )
        verify(summary.warning_count == 1)
        verify(summary.redemption_attempt_count == 0)

    thresholds: list[int] = []
    for event in read_events(db_path):
        if event.get("event_type") != "expiry_warning":
            continue
        thresholds.append(
            required_integer(
                event.get("threshold_hours"),
                label="warning threshold hours",
            ),
        )
    verify(thresholds == [48, 24, 6, 2, 1])


def test_failed_live_warning_notification_retries_without_duplicate_warning(
    tmp_path: Path,
) -> None:
    """Retry a failed notification without duplicating its warning event."""
    now = datetime(2026, 8, 10, 21, 15, tzinfo=UTC)
    source = SimulationSource(
        guardian_fixture(expires_at=now + timedelta(hours=23, minutes=53)),
        clock=lambda: now,
    )

    notifier_messages: list[str] = []

    def flaky_notifier(message: str) -> None:
        notifier_messages.append(message)
        verify("24h threshold" in message)
        if len(notifier_messages) == 1:
            error_code = "temporary_failure"
            raise NotificationError(error_code)

    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        first = Guardian(
            source=source,
            audit=audit,
            notifier=flaky_notifier,
            clock=lambda: now,
        ).run(mode="live", dry_run=True)
    with AuditStore(db_path) as audit:
        second = Guardian(
            source=source,
            audit=audit,
            notifier=flaky_notifier,
            clock=lambda: now,
        ).run(mode="live", dry_run=True)

    verify(first.warning_count == EXPECTED_RETRY_NOTIFICATION_COUNT)
    verify(first.notification_error_count == 1)
    verify(first.status == "degraded")
    verify(second.warning_count == 0)
    verify(second.notification_error_count == 0)
    verify(second.status == "ok")
    verify(len(notifier_messages) == EXPECTED_RETRY_NOTIFICATION_COUNT)
    with sqlite3.connect(db_path) as connection:
        verify(
            count_rows(connection, "SELECT count(*) FROM warning_marks")
            == EXPECTED_RETRY_NOTIFICATION_COUNT,
        )
        verify(
            count_rows(
                connection,
                "SELECT count(*) FROM events WHERE event_type = 'expiry_warning'",
            )
            == EXPECTED_RETRY_NOTIFICATION_COUNT,
        )
        verify(
            count_rows(
                connection,
                "SELECT count(*) FROM notifications WHERE status = 'sent' AND attempts = 2",
            )
            == EXPECTED_RETRY_NOTIFICATION_COUNT,
        )
        verify(
            count_rows(
                connection,
                "SELECT count(*) FROM events WHERE event_type = 'notification_failed'",
            )
            == 1,
        )
        verify(
            count_rows(
                connection,
                "SELECT count(*) FROM events WHERE event_type = 'notification_sent'",
            )
            == 1,
        )


def test_same_credit_id_and_expiry_are_scoped_per_account_for_warnings(
    tmp_path: Path,
) -> None:
    """Scope otherwise identical warning identities to their provider accounts."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    fixture = guardian_fixture(
        expires_at=now + timedelta(hours=5),
        credit_id="shared-provider-id",
    )
    accounts = required_array(fixture, "accounts")
    second = deepcopy(required_array_object(accounts, 0))
    second["label"] = "support@pitchai.net"
    accounts.append(second)
    source = SimulationSource(fixture, clock=lambda: now)

    messages: list[str] = []

    def record_notification(message: str) -> None:
        messages.append(message)

    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        guardian = Guardian(
            source=source,
            audit=audit,
            notifier=record_notification,
            clock=lambda: now,
        )
        summary = guardian.run(mode="live", dry_run=True)

    verify(summary.warning_count == EXPECTED_SCOPED_WARNING_COUNT)
    verify(summary.redemption_attempt_count == 0)
    verify(len(messages) == 1)
    verify("info@pitchai.net" in messages[0])
    verify("support@pitchai.net" in messages[0])
    with sqlite3.connect(db_path) as connection:
        verify(
            count_rows(connection, "SELECT count(*) FROM warning_marks")
            == EXPECTED_SCOPED_WARNING_COUNT,
        )
        verify(
            count_rows(
                connection,
                "SELECT count(DISTINCT account_ref) FROM warning_marks",
            )
            == EXPECTED_SCOPED_ACCOUNT_COUNT,
        )
        verify(
            count_rows(connection, "SELECT count(*) FROM notifications")
            == EXPECTED_SCOPED_WARNING_COUNT,
        )
