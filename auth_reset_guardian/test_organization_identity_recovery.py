# Copyright (c) 2026 PitchAI. All rights reserved.
"""Restart proofs for exact expiry and weekly-reset claim identity."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .clients import RemoteCallError
from .organization_claim import row_text
from .test_organization_support import (
    NOW,
    SequencedSource,
    account_observation,
    database_rows,
    require_equal,
    reset_credit,
    run_guardian,
)

if TYPE_CHECKING:
    from pathlib import Path


def ambiguous_timeout() -> RemoteCallError:
    """Build the transport-ambiguous result used by restart tests.

    Returns:
        A provider-call timeout whose mutation outcome is unknown.
    """
    return RemoteCallError(
        endpoint="provider_consume_reset_credit",
        error_code="transport_timeout",
        ambiguous=True,
    )


def test_restart_rejects_same_opaque_id_with_changed_expiry(tmp_path: Path) -> None:
    """Retire the old identity loudly and suppress all consume on that pass."""
    later = NOW + timedelta(minutes=15)
    weekly_reset = NOW + timedelta(days=7)
    expiry = NOW + timedelta(days=10)
    credit = reset_credit("reissued-reset", expires_at=expiry)
    changed = reset_credit("reissued-reset", expires_at=expiry + timedelta(hours=1))
    initial = account_observation(
        "elise@pitchai.net",
        weekly_reset_at=weekly_reset,
        credit_bank=(credit,),
    )
    reissued = account_observation(
        "elise@pitchai.net",
        captured_at=later,
        weekly_reset_at=weekly_reset,
        credit_bank=(changed,),
    )
    source = SequencedSource(
        (initial.descriptor,),
        {initial.descriptor.account_ref: [initial, initial, reissued]},
        [ambiguous_timeout()],
    )
    db_path = tmp_path / "audit.sqlite3"

    _ = run_guardian(db_path, source=source, now=NOW)
    second = run_guardian(db_path, source=source, now=later)

    require_equal(second.error_count, 1)
    require_equal(len(source.consume_calls), 1)
    attempts = database_rows(
        db_path,
        "SELECT status, verification, error_code FROM redemption_attempts",
    )
    require_equal(row_text(attempts[0], "status"), "identity_mismatch")
    require_equal(
        row_text(attempts[0], "verification"),
        "credit_ref_reissued_with_changed_expiry",
    )
    require_equal(row_text(attempts[0], "error_code"), "exact_credit_expiry_changed")
    events = database_rows(
        db_path,
        "SELECT severity FROM events WHERE event_type = 'pending_redemption_identity_mismatch'",
    )
    require_equal(len(events), 1)
    require_equal(row_text(events[0], "severity"), "error")


def test_restart_retires_claim_when_selected_weekly_reset_changes(
    tmp_path: Path,
) -> None:
    """Never reuse an ambiguous attempt after its selected weekly identity moves."""
    later = NOW + timedelta(minutes=15)
    expiry = NOW + timedelta(days=10)
    credit = reset_credit("weekly-shift-reset", expires_at=expiry)
    initial = account_observation(
        "elise@pitchai.net",
        weekly_reset_at=NOW + timedelta(days=7),
        credit_bank=(credit,),
    )
    changed = account_observation(
        "elise@pitchai.net",
        captured_at=later,
        weekly_reset_at=NOW + timedelta(days=7, hours=1),
        credit_bank=(credit,),
    )
    source = SequencedSource(
        (initial.descriptor,),
        {initial.descriptor.account_ref: [initial, initial, changed]},
        [ambiguous_timeout()],
    )
    db_path = tmp_path / "audit.sqlite3"

    _ = run_guardian(db_path, source=source, now=NOW)
    second = run_guardian(db_path, source=source, now=later)

    require_equal(second.error_count, 1)
    require_equal(len(source.consume_calls), 1)
    attempts = database_rows(
        db_path,
        "SELECT status, verification, error_code FROM redemption_attempts",
    )
    require_equal(row_text(attempts[0], "status"), "identity_mismatch")
    require_equal(
        row_text(attempts[0], "verification"),
        "fresh_policy_selected_different_exact_target",
    )
    require_equal(row_text(attempts[0], "error_code"), "active_selection_mismatch")
