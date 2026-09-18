# Copyright (c) 2026 PitchAI. All rights reserved.
"""Concurrency and restart-recovery proofs for organization redemption."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from threading import Barrier
from typing import TYPE_CHECKING

from .audit import AuditStore
from .clients import RemoteCallError
from .models import ConsumeResult
from .organization_audit import OrganizationAttemptStore
from .organization_claim import ClaimRequest, row_text
from .organization_policy import evaluate_organization
from .test_organization_support import (
    NOW,
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

    from .organization_claim import CoordinatedAttempt


def claim_concurrently(
    db_path: Path,
    requests: tuple[ClaimRequest, ...],
) -> tuple[CoordinatedAttempt, ...]:
    """Race coordinated claims through separate SQLite connections.

    Returns:
        Each worker's view of the one durable attempt.
    """
    barrier = Barrier(len(requests))

    def take_claim(request: ClaimRequest) -> CoordinatedAttempt:
        _ = barrier.wait()
        with closing(OrganizationAttemptStore(db_path)) as claims:
            return claims.claim(request)

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return tuple(executor.map(take_claim, requests))


def test_concurrent_workers_share_one_executable_attempt(tmp_path: Path) -> None:
    """Fence two simultaneous workers with one durable organization claim."""
    db_path = tmp_path / "audit.sqlite3"
    credit = reset_credit("concurrent-reset", expires_at=NOW + timedelta(days=10))
    observation = account_observation("elise@pitchai.net", credit_bank=(credit,))
    decision = evaluate_organization(
        descriptors=[observation.descriptor],
        observations={observation.descriptor.account_ref: observation},
        failed_account_refs=set(),
        now=NOW,
    )
    selection = decision.selection
    require(
        condition=selection is not None,
        message="concurrency fixture was not eligible",
    )
    if selection is None:
        return
    with AuditStore(db_path) as audit:
        run_ids = tuple(audit.start_run(mode="live", now=NOW) for _index in range(2))
    with closing(OrganizationAttemptStore(db_path)):
        pass
    requests = tuple(
        ClaimRequest(
            run_id=run_id,
            now=NOW,
            decision_key=decision.decision_key,
            selection=selection,
        )
        for run_id in run_ids
    )
    attempts = claim_concurrently(db_path, requests)

    executable_count = sum(item.executable for item in attempts)
    attempt_ids = {item.attempt_id for item in attempts}
    idempotency_keys = {item.idempotency_key for item in attempts}
    require_equal(executable_count, 1)
    require_equal(len(attempt_ids), 1)
    require_equal(len(idempotency_keys), 1)
    rows = database_rows(
        db_path,
        "SELECT count(*) AS row_count FROM redemption_attempts",
    )
    require_equal(len(rows), 1)
    require_equal(row_integer(rows[0], "row_count"), 1)


def test_ambiguous_restart_reuses_key_only_after_fresh_provider_reconciliation(
    tmp_path: Path,
) -> None:
    """Resume one uncertain logical attempt after a new authoritative scan."""
    later = NOW + timedelta(minutes=15)
    weekly_reset = NOW + timedelta(days=7)
    credit = reset_credit("ambiguous-reset", expires_at=NOW + timedelta(days=10))
    initial = account_observation(
        "elise@pitchai.net",
        weekly_reset_at=weekly_reset,
        credit_bank=(credit,),
    )
    later_state = account_observation(
        "elise@pitchai.net",
        captured_at=later,
        weekly_reset_at=weekly_reset,
        credit_bank=(credit,),
    )
    source = SequencedSource(
        (initial.descriptor,),
        {
            initial.descriptor.account_ref: [
                initial,
                initial,
                later_state,
                later_state,
                later_state,
            ],
        },
        [
            RemoteCallError(
                endpoint="provider_consume_reset_credit",
                error_code="transport_timeout",
                ambiguous=True,
            ),
            ConsumeResult(code="nothing_to_reset", windows_reset=0),
        ],
    )
    db_path = tmp_path / "audit.sqlite3"
    first = run_guardian(db_path, source=source, now=NOW)
    second = run_guardian(db_path, source=source, now=later)
    require_equal(first.error_count, 1)
    require_equal(second.error_count, 0)
    require_equal(len(source.consume_calls), 2)
    require_equal(source.consume_calls[0][2], source.consume_calls[1][2])
    attempts = database_rows(
        db_path,
        "SELECT attempt_id, idempotency_key, status, outcome FROM redemption_attempts",
    )
    require_equal(len(attempts), 1)
    require_equal(row_text(attempts[0], "status"), "completed")
    require_equal(row_text(attempts[0], "outcome"), "nothing_to_reset")
    resumed = database_rows(
        db_path,
        """
        SELECT events.run_id
          FROM events
          JOIN runs USING (run_id)
         WHERE event_type = 'redemption_attempt_started'
           AND json_extract(details_json, '$.resumed') = 1
           AND EXISTS (
               SELECT 1 FROM snapshots
                WHERE snapshots.run_id = events.run_id
                  AND snapshots.phase = 'initial_inventory'
           )
        """,
    )
    require_equal(len(resumed), 1)


def test_restart_reconciles_absent_credit_without_retrying_consume(
    tmp_path: Path,
) -> None:
    """Treat provider-confirmed absence as terminal before any ambiguous retry."""
    later = NOW + timedelta(minutes=15)
    weekly_reset = NOW + timedelta(days=7)
    credit = reset_credit("lost-response-reset", expires_at=NOW + timedelta(days=10))
    initial = account_observation(
        "elise@pitchai.net",
        weekly_reset_at=weekly_reset,
        credit_bank=(credit,),
    )
    absent = account_observation(
        "elise@pitchai.net",
        captured_at=later,
        weekly_reset_at=weekly_reset,
    )
    source = SequencedSource(
        (initial.descriptor,),
        {initial.descriptor.account_ref: [initial, initial, absent]},
        [
            RemoteCallError(
                endpoint="provider_consume_reset_credit",
                error_code="transport_timeout",
                ambiguous=True,
            ),
        ],
    )
    db_path = tmp_path / "audit.sqlite3"
    _ = run_guardian(db_path, source=source, now=NOW)
    summary = run_guardian(db_path, source=source, now=later)

    require_equal(len(source.consume_calls), 1)
    require_equal(summary.redemption_count, 1)
    attempts = database_rows(
        db_path,
        "SELECT status, verification FROM redemption_attempts",
    )
    require_equal(row_text(attempts[0], "status"), "reconciled_absent")
    require_equal(
        row_text(attempts[0], "verification"),
        "credit_absent_on_later_fresh_scan",
    )
