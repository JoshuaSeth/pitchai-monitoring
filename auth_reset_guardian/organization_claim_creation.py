# Copyright (c) 2026 PitchAI. All rights reserved.
"""Atomic row creation for a new organization redemption attempt."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

from .models import utc_iso
from .organization_claim import CoordinatedAttempt

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from .organization_claim import ClaimRequest


def insert_attempt(
    connection: sqlite3.Connection,
    request: ClaimRequest,
    *,
    lease_until: datetime,
) -> CoordinatedAttempt:
    """Insert linked attempt and claim rows inside the caller's transaction.

    Returns:
        A newly executable durable attempt.

    Raises:
        ValueError: The selected credit lacks an expiry.
    """
    selection = request.selection
    expires_at = selection.credit.expires_at
    if expires_at is None:
        message = "organization selection requires an expiring credit"
        raise ValueError(message)
    attempt_id = uuid4().hex
    idempotency_key = (
        f"pitchai-reset-guardian:{selection.credit.credit_ref[:20]}:{attempt_id}"
    )
    now_text = utc_iso(request.now)
    details: dict[str, object] = {
        "coordination_key": request.decision_key,
        "weekly_reset_at": utc_iso(selection.weekly_reset_at),
        "policy": "automatic_organization_exhaustion",
    }
    _ = connection.execute(
        """
        INSERT INTO redemption_attempts(
            attempt_id, idempotency_key, run_id, account_ref, account_label,
            credit_ref, expires_at, reason, started_at, updated_at, status, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'automatic_organization_exhaustion', ?, ?, 'started', ?)
        """,
        (
            attempt_id,
            idempotency_key,
            request.run_id,
            selection.observation.descriptor.account_ref,
            selection.observation.descriptor.label,
            selection.credit.credit_ref,
            utc_iso(expires_at),
            now_text,
            now_text,
            json.dumps(details, sort_keys=True, separators=(",", ":")),
        ),
    )
    claim_id = uuid4().hex
    _ = connection.execute(
        """
        INSERT INTO organization_redemption_claims(
            claim_id, scope, decision_key, attempt_id, account_ref, credit_ref,
            expires_at, weekly_reset_at, state, lease_owner, lease_until,
            created_at, updated_at
        ) VALUES (?, 'organization', ?, ?, ?, ?, ?, ?, 'claimed', ?, ?, ?, ?)
        """,
        (
            claim_id,
            request.decision_key,
            attempt_id,
            selection.observation.descriptor.account_ref,
            selection.credit.credit_ref,
            utc_iso(expires_at),
            utc_iso(selection.weekly_reset_at),
            request.run_id,
            utc_iso(lease_until),
            now_text,
            now_text,
        ),
    )
    return CoordinatedAttempt(
        attempt_id=attempt_id,
        idempotency_key=idempotency_key,
        resumed=False,
        executable=True,
        status="started",
    )
