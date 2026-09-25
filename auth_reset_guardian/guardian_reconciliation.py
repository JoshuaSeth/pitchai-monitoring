# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reconcile unfinished guardian attempts against fresh account state."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from .guardian_types import Alert
from .models import parse_timestamp

if TYPE_CHECKING:
    from .guardian_types import GuardianDependencies, RunContext
    from .models import AccountObservation


def reconcile_pending_attempts(
    dependencies: GuardianDependencies,
    context: RunContext,
    observation: AccountObservation,
) -> None:
    """Resolve unfinished attempts when an exact credit later disappears."""
    available_refs: set[str] = set()
    for credit in observation.credits:
        if credit.is_redeemable:
            available_refs.add(credit.credit_ref)
    pending_attempts = dependencies.audit.pending_attempts_for_account(
        account_ref=observation.descriptor.account_ref,
    )
    for pending in pending_attempts:
        if pending.credit_ref in available_refs:
            continue
        expiry = parse_timestamp(pending.expires_at, field_name="attempt.expires_at")
        if dependencies.clock() >= expiry:
            status = "expired_unverified"
            verification = "credit_absent_only_after_expiry"
            severity = "error"
            context.summary.error_count += 1
        else:
            status = "reconciled_absent"
            verification = "credit_absent_on_later_fresh_scan"
            severity = "info"
            context.summary.redemption_count += 1
        dependencies.audit.update_attempt(
            attempt_id=pending.attempt_id,
            now=dependencies.clock(),
            status=status,
            outcome=pending.outcome,
            windows_reset=pending.windows_reset,
            verification=verification,
        )
        dependencies.audit.record_event(
            run_id=context.run_id,
            now=dependencies.clock(),
            event_type="redemption_attempt_reconciled",
            severity=severity,
            account_ref=observation.descriptor.account_ref,
            account_label=observation.descriptor.label,
            credit_ref=pending.credit_ref,
            expires_at=expiry,
            attempt_id=pending.attempt_id,
            details={"status": status, "verification": verification},
        )
        label = html.escape(observation.descriptor.label)
        prefix = "SUCCESS" if severity == "info" else "ERROR"
        context.alerts.append(
            Alert(
                key=f"attempt-reconciled:{pending.attempt_id}:{status}",
                line=(f"{prefix} {label} pending reset attempt {pending.attempt_id[:12]} reconciled as {status}."),
            ),
        )
