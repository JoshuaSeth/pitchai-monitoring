# Copyright (c) 2026 PitchAI. All rights reserved.
"""Notification and definite-outcome retry proofs."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from .models import ConsumeResult
from .organization_claim import row_text
from .test_organization_support import (
    NOW,
    RecordingNotifier,
    SequencedSource,
    account_observation,
    database_rows,
    require,
    require_equal,
    reset_credit,
    row_integer,
    run_guardian,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_nothing_to_reset_uses_new_key_and_sends_one_scoped_waiting_alert(
    tmp_path: Path,
) -> None:
    """Retry a definite no-op as a new attempt while suppressing repeat alerts."""
    later = NOW + timedelta(minutes=15)
    weekly_reset = NOW + timedelta(days=7)
    credit = reset_credit("waiting-reset", expires_at=NOW + timedelta(days=10))
    first_state = account_observation(
        "elise@pitchai.net",
        weekly_reset_at=weekly_reset,
        credit_bank=(credit,),
    )
    later_state = replace(first_state, captured_at=later)
    source = SequencedSource(
        (first_state.descriptor,),
        {
            first_state.descriptor.account_ref: [
                first_state,
                first_state,
                first_state,
                later_state,
                later_state,
                later_state,
            ],
        },
        [
            ConsumeResult(code="nothing_to_reset", windows_reset=0),
            ConsumeResult(code="nothing_to_reset", windows_reset=0),
        ],
    )
    notifier = RecordingNotifier()
    db_path = tmp_path / "audit.sqlite3"

    _ = run_guardian(db_path, source=source, now=NOW, notifier=notifier)
    _ = run_guardian(db_path, source=source, now=later, notifier=notifier)

    require_equal(len(source.consume_calls), 2)
    require(
        condition=source.consume_calls[0][2] != source.consume_calls[1][2],
        message="retry reused a definite key",
    )
    require_equal(notifier.message_count(), 1)
    require(
        condition="nothing_to_reset" in notifier.messages[0],
        message="waiting outcome was not reported",
    )
    attempts = database_rows(
        db_path,
        "SELECT attempt_id, idempotency_key, status FROM redemption_attempts ORDER BY started_at",
    )
    require_equal(len(attempts), 2)
    statuses = tuple(row_text(row, "status") for row in attempts)
    require_equal(statuses, ("completed", "completed"))
    notifications = database_rows(
        db_path,
        """
        SELECT status, attempts
          FROM notifications
         WHERE notification_key LIKE 'redemption-waiting:%:nothing_to_reset'
        """,
    )
    require_equal(len(notifications), 1)
    require_equal(row_text(notifications[0], "status"), "sent")
    require_equal(row_integer(notifications[0], "attempts"), 1)
