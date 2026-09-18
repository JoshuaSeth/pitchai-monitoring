# Copyright (c) 2026 PitchAI. All rights reserved.
"""End-to-end workflow safety proofs for organization reset redemption."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .models import ConsumeResult, utc_iso
from .organization_claim import row_text
from .test_organization_support import (
    NOW,
    SequencedSource,
    account_observation,
    database_rows,
    require_equal,
    reset_credit,
    row_integer,
    run_guardian,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_success_requires_exact_identity_then_proves_capacity_restored(
    tmp_path: Path,
) -> None:
    """Persist both rechecks, target once, and verify usable post-capacity."""
    expiry = NOW + timedelta(days=10)
    credit = reset_credit("elise-eligible-reset", expires_at=expiry)
    exhausted = account_observation(
        "elise@pitchai.net",
        weekly_reset_at=NOW + timedelta(days=7),
        credit_bank=(credit,),
    )
    restored = account_observation(
        "elise@pitchai.net",
        used_percent=0,
        weekly_reset_at=NOW + timedelta(days=7),
    )
    source = SequencedSource(
        (exhausted.descriptor,),
        {exhausted.descriptor.account_ref: [exhausted, exhausted, restored, restored]},
        [ConsumeResult(code="reset", windows_reset=2)],
    )
    db_path = tmp_path / "audit.sqlite3"

    summary = run_guardian(db_path, source=source, now=NOW)

    require_equal(summary.status, "ok")
    require_equal(summary.redemption_attempt_count, 1)
    require_equal(summary.redemption_count, 1)
    require_equal(len(source.consume_calls), 1)
    require_equal(source.consume_calls[0][0], exhausted.descriptor.account_ref)
    require_equal(source.consume_calls[0][1], credit.credit_ref)
    snapshots = database_rows(
        db_path,
        """
        SELECT phase, account_ref,
               json_extract(state_json, '$.credits[0].credit_ref') AS credit_ref,
               json_extract(state_json, '$.credits[0].expires_at') AS expires_at
          FROM snapshots
         WHERE phase IN ('initial_inventory', 'pre_redemption_recheck')
         ORDER BY snapshot_id
        """,
    )
    require_equal(len(snapshots), 2)
    for row in snapshots:
        require_equal(row_text(row, "account_ref"), exhausted.descriptor.account_ref)
        require_equal(row_text(row, "credit_ref"), credit.credit_ref)
        require_equal(row_text(row, "expires_at"), utc_iso(expiry))
    attempts = database_rows(
        db_path,
        """
        SELECT account_ref, credit_ref, expires_at, reason, outcome, status,
               verification, windows_reset
          FROM redemption_attempts
        """,
    )
    require_equal(len(attempts), 1)
    attempt = attempts[0]
    require_equal(row_text(attempt, "reason"), "automatic_organization_exhaustion")
    require_equal(row_text(attempt, "outcome"), "reset")
    require_equal(row_text(attempt, "status"), "succeeded")
    require_equal(row_text(attempt, "verification"), "exact_credit_absent")
    require_equal(row_integer(attempt, "windows_reset"), 2)


def test_same_opaque_credit_with_changed_expiry_fails_loudly_before_consume(
    tmp_path: Path,
) -> None:
    """Bind the irreversible target to account, exact credit, and exact expiry."""
    expiry = NOW + timedelta(days=10)
    changed_expiry = expiry + timedelta(hours=1)
    credit = reset_credit("same-opaque-reset", expires_at=expiry)
    changed_credit = reset_credit(
        "same-opaque-reset",
        expires_at=changed_expiry,
    )
    initial = account_observation("elise@pitchai.net", credit_bank=(credit,))
    changed = account_observation("elise@pitchai.net", credit_bank=(changed_credit,))
    source = SequencedSource(
        (initial.descriptor,),
        {initial.descriptor.account_ref: [initial, changed]},
        [],
    )
    db_path = tmp_path / "audit.sqlite3"

    summary = run_guardian(db_path, source=source, now=NOW)

    require_equal(summary.redemption_attempt_count, 0)
    require_equal(summary.redemption_count, 0)
    require_equal(summary.error_count, 1)
    require_equal(len(source.consume_calls), 0)
    attempts = database_rows(
        db_path,
        "SELECT status, verification, error_code FROM redemption_attempts",
    )
    require_equal(len(attempts), 1)
    require_equal(row_text(attempts[0], "status"), "cancelled_before_consume")
    require_equal(row_text(attempts[0], "error_code"), "exact_credit_expiry_changed")
    events = database_rows(
        db_path,
        """
        SELECT severity,
               json_extract(details_json, '$.reason') AS reason,
               json_extract(details_json, '$.expected_expires_at') AS expected,
               json_extract(details_json, '$.fresh_expires_at') AS fresh
          FROM events
         WHERE event_type = 'organization_redemption_suppressed_after_recheck'
        """,
    )
    require_equal(len(events), 1)
    require_equal(row_text(events[0], "severity"), "error")
    require_equal(row_text(events[0], "reason"), "exact_credit_expiry_changed")
    require_equal(row_text(events[0], "expected"), utc_iso(expiry))
    require_equal(row_text(events[0], "fresh"), utc_iso(changed_expiry))


def test_fresh_returned_capacity_cancels_claim_without_consuming(
    tmp_path: Path,
) -> None:
    """Suppress a stale initial trigger when any capacity returns on recheck."""
    credit = reset_credit("capacity-race-reset", expires_at=NOW + timedelta(days=10))
    exhausted = account_observation("elise@pitchai.net", credit_bank=(credit,))
    recovered = account_observation(
        "elise@pitchai.net",
        used_percent=99,
        credit_bank=(credit,),
    )
    source = SequencedSource(
        (exhausted.descriptor,),
        {exhausted.descriptor.account_ref: [exhausted, recovered]},
        [],
    )
    db_path = tmp_path / "audit.sqlite3"

    summary = run_guardian(db_path, source=source, now=NOW)

    require_equal(summary.redemption_attempt_count, 0)
    require_equal(len(source.consume_calls), 0)
    events = database_rows(
        db_path,
        """
        SELECT json_extract(details_json, '$.reason') AS reason
          FROM events
         WHERE event_type = 'organization_redemption_suppressed_after_recheck'
        """,
    )
    require_equal(len(events), 1)
    require_equal(
        row_text(events[0], "reason"),
        "fresh_organization_state_not_exhausted",
    )
