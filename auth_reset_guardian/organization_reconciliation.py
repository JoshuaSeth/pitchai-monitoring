# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exact-identity reconciliation for unfinished organization attempts."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, cast

from .guardian import Alert
from .models import parse_timestamp, utc_iso

if TYPE_CHECKING:
    from datetime import datetime

    from .models import AccountObservation, ResetCredit
    from .organization_runtime import OrganizationRunContext


@dataclass(frozen=True)
class PendingAttempt:
    """Typed identity and prior outcome for one unfinished attempt."""

    attempt_id: str
    credit_ref: str
    expires_at: datetime
    outcome: str | None
    windows_reset: int | None


class PendingAttemptRecord(TypedDict):
    """Untrusted values returned from the legacy audit query."""

    attempt_id: object
    credit_ref: object
    expires_at: object
    outcome: object
    windows_reset: object


def reconcile_pending_attempts(
    context: OrganizationRunContext,
    observation: AccountObservation,
) -> bool:
    """Reconcile unfinished attempts and detect an exact-identity mismatch.

    Returns:
        True when an old opaque ID now carries a different expiry.
    """
    raw_attempts = context.audit.pending_attempts_for_account(
        account_ref=observation.descriptor.account_ref,
    )
    identity_mismatch = False
    for raw_attempt in raw_attempts:
        record = cast("PendingAttemptRecord", cast("object", raw_attempt))
        pending = _pending_attempt(record)
        credit = observation.find_credit(pending.credit_ref)
        if credit is not None and credit.is_redeemable:
            if credit.expires_at == pending.expires_at:
                continue
            _record_identity_mismatch(context, observation, pending, credit)
            identity_mismatch = True
            continue
        _record_terminal_reconciliation(context, observation, pending)
    return identity_mismatch


def _pending_attempt(record: PendingAttemptRecord) -> PendingAttempt:
    attempt_id = record["attempt_id"]
    credit_ref = record["credit_ref"]
    if not isinstance(attempt_id, str) or not attempt_id:
        message = "pending attempt ID is not text"
        raise TypeError(message)
    if not isinstance(credit_ref, str) or not credit_ref:
        message = "pending credit reference is not text"
        raise TypeError(message)
    expires_at = parse_timestamp(
        record.get("expires_at"),
        field_name="attempt.expires_at",
    )
    outcome_value = record.get("outcome")
    outcome = outcome_value if isinstance(outcome_value, str) else None
    windows_value = record.get("windows_reset")
    windows_reset = (
        windows_value
        if isinstance(windows_value, int) and not isinstance(windows_value, bool)
        else None
    )
    return PendingAttempt(attempt_id, credit_ref, expires_at, outcome, windows_reset)


def _record_identity_mismatch(
    context: OrganizationRunContext,
    observation: AccountObservation,
    pending: PendingAttempt,
    credit: ResetCredit,
) -> None:
    verification = "credit_ref_reissued_with_changed_expiry"
    fresh_expiry = utc_iso(credit.expires_at) if credit.expires_at else None
    context.audit.update_attempt(
        attempt_id=pending.attempt_id,
        now=context.clock(),
        status="identity_mismatch",
        outcome=pending.outcome,
        windows_reset=pending.windows_reset,
        verification=verification,
        error_code="exact_credit_expiry_changed",
        details={
            "consume_attempted": False,
            "expected_expires_at": utc_iso(pending.expires_at),
            "fresh_expires_at": fresh_expiry,
        },
    )
    context.summary.error_count += 1
    descriptor = observation.descriptor
    context.audit.record_event(
        run_id=context.run_id,
        now=context.clock(),
        event_type="pending_redemption_identity_mismatch",
        severity="error",
        account_ref=descriptor.account_ref,
        account_label=descriptor.label,
        credit_ref=pending.credit_ref,
        expires_at=pending.expires_at,
        attempt_id=pending.attempt_id,
        details={
            "verification": verification,
            "expected_expires_at": utc_iso(pending.expires_at),
            "fresh_expires_at": fresh_expiry,
            "consume_attempted": False,
        },
    )
    line = (
        f"ERROR {html.escape(descriptor.label)} pending reset reused its opaque ID "
        "with a changed expiry; "
        "this pass cannot consume it."
    )
    context.alerts.append(
        Alert(key=f"pending-expiry-mismatch:{pending.attempt_id}", line=line),
    )


def _record_terminal_reconciliation(
    context: OrganizationRunContext,
    observation: AccountObservation,
    pending: PendingAttempt,
) -> None:
    expired = context.clock() >= pending.expires_at
    status = "expired_unverified" if expired else "reconciled_absent"
    verification = (
        "credit_absent_only_after_expiry"
        if expired
        else "credit_absent_on_later_fresh_scan"
    )
    severity = "error" if expired else "info"
    if expired:
        context.summary.error_count += 1
    else:
        context.summary.redemption_count += 1
    context.audit.update_attempt(
        attempt_id=pending.attempt_id,
        now=context.clock(),
        status=status,
        outcome=pending.outcome,
        windows_reset=pending.windows_reset,
        verification=verification,
    )
    descriptor = observation.descriptor
    context.audit.record_event(
        run_id=context.run_id,
        now=context.clock(),
        event_type="redemption_attempt_reconciled",
        severity=severity,
        account_ref=descriptor.account_ref,
        account_label=descriptor.label,
        credit_ref=pending.credit_ref,
        expires_at=pending.expires_at,
        attempt_id=pending.attempt_id,
        details={"status": status, "verification": verification},
    )
    prefix = "ERROR" if expired else "SUCCESS"
    line = (
        f"{prefix} {html.escape(descriptor.label)} pending reset "
        f"{pending.attempt_id[:12]} reconciled as {status}."
    )
    context.alerts.append(
        Alert(key=f"attempt-reconciled:{pending.attempt_id}:{status}", line=line),
    )
