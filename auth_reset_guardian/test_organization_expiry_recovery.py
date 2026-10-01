# Copyright (c) 2026 PitchAI. All rights reserved.
"""An expiry-priority change cannot release an unresolved consume claim."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from .audit import AuditStore
from .models import ConsumeResult
from .organization_claim import row_text
from .test_organization_expiry import with_end
from .test_organization_identity_recovery import ambiguous_timeout
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


def test_new_preferred_account_cannot_retire_unresolved_consume(tmp_path: Path) -> None:
    """Keep the original fence across both a live lease and an expired lease."""
    credit = reset_credit("original", expires_at=NOW + timedelta(days=10))
    other_credit = reset_credit("other", expires_at=NOW + timedelta(days=20))
    original = account_observation("original@example.test", credit_bank=(credit,))
    other = account_observation("other@example.test", credit_bank=(other_credit,))
    source = SequencedSource(
        (original.descriptor, other.descriptor),
        {
            original.descriptor.account_ref: [original],
            other.descriptor.account_ref: [other],
        },
        [ambiguous_timeout()],
    )
    db_path = tmp_path / "audit.sqlite3"
    _ = run_guardian(db_path, source=source, now=NOW)
    for offset in (1, 15, 30):
        later = NOW + timedelta(minutes=offset)
        preferred = with_end(replace(other, captured_at=later), "2026-09-08")
        fresh_original = replace(original, captured_at=later)
        retry_source = SequencedSource(
            (original.descriptor, other.descriptor),
            {
                original.descriptor.account_ref: [fresh_original],
                other.descriptor.account_ref: [preferred],
            },
            [],
        )
        _ = run_guardian(db_path, source=retry_source, now=later)
        require_equal(len(retry_source.consume_calls), 0)
    claims = database_rows(db_path, "SELECT state FROM organization_redemption_claims")
    require_equal(len(claims), 1)
    require_equal(row_text(claims[0], "state"), "uncertain")


def test_expired_pending_credit_reconciles_even_when_provider_still_lists_available(tmp_path: Path) -> None:
    """An expired listed credit cannot trap the durable fence or be replayed."""
    credit = reset_credit("expires", expires_at=NOW + timedelta(minutes=5))
    initial = account_observation("account@example.test", credit_bank=(credit,))
    later = NOW + timedelta(minutes=15)
    expired = replace(initial, captured_at=later)
    source = SequencedSource(
        (initial.descriptor,),
        {initial.descriptor.account_ref: [initial, initial, expired]},
        [ambiguous_timeout()],
    )
    db_path = tmp_path / "audit.sqlite3"
    _ = run_guardian(db_path, source=source, now=NOW)
    _ = run_guardian(db_path, source=source, now=later)
    require_equal(len(source.consume_calls), 1)
    claims = database_rows(db_path, "SELECT state FROM organization_redemption_claims")
    require_equal(row_text(claims[0], "state"), "expired_unverified")


def test_success_cannot_replay_when_subscription_ordering_changes(tmp_path: Path) -> None:
    """A new policy decision key cannot consume a previously completed identity."""
    credit = reset_credit("completed", expires_at=NOW + timedelta(days=10))
    initial = account_observation("account@example.test", credit_bank=(credit,))
    post = account_observation("account@example.test", used_percent=0)
    later = NOW + timedelta(minutes=15)
    relisted = with_end(replace(initial, captured_at=later), "2026-09-08")
    source = SequencedSource(
        (initial.descriptor,),
        {initial.descriptor.account_ref: [initial, initial, post, post, relisted]},
        [ConsumeResult(code="reset", windows_reset=1)],
    )
    db_path = tmp_path / "audit.sqlite3"
    _ = run_guardian(db_path, source=source, now=NOW)
    _ = run_guardian(db_path, source=source, now=later)
    require_equal(len(source.consume_calls), 1)


def test_legacy_success_without_organization_claim_cannot_replay(tmp_path: Path) -> None:
    """Preserve completed August history when adopting the new ordering policy."""
    credit = reset_credit("legacy-completed", expires_at=NOW + timedelta(days=10))
    observation = account_observation("account@example.test", credit_bank=(credit,))
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        run_id = audit.start_run(mode="live", now=NOW)
        attempt = audit.start_or_resume_attempt(
            run_id=run_id, now=NOW, observation=observation, credit=credit, reason="legacy",
        )
        audit.update_attempt(attempt_id=attempt.attempt_id, now=NOW, status="succeeded")
    source = SequencedSource(
        (observation.descriptor,), {observation.descriptor.account_ref: [observation]}, [],
    )
    _ = run_guardian(db_path, source=source, now=NOW)
    require_equal(len(source.consume_calls), 0)
