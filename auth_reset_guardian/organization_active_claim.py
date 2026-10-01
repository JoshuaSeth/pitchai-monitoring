# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep an unresolved mutation fenced when expiry ordering changes the target."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .guardian import Alert

if TYPE_CHECKING:
    from .organization_claim import CoordinatedAttempt
    from .organization_policy import RedemptionSelection
    from .organization_runtime import OrganizationRunContext


def resolve_active_mismatch(
    context: OrganizationRunContext,
    attempt: CoordinatedAttempt,
    selection: RedemptionSelection,
) -> None:
    """Suppress a different target until the original mutation is reconciled."""
    verification = "fresh_policy_selected_different_exact_target"
    context.summary.error_count += 1
    descriptor = selection.observation.descriptor
    context.audit.record_event(
        run_id=context.run_id,
        now=context.clock(),
        event_type="organization_active_claim_identity_mismatch",
        severity="error",
        account_ref=descriptor.account_ref,
        account_label=descriptor.label,
        credit_ref=selection.credit.credit_ref,
        expires_at=selection.credit.expires_at,
        attempt_id=attempt.attempt_id,
        details={"verification": verification, "consume_attempted": False},
    )
    line = (
        "ERROR a prior ambiguous reset claim no longer matches the fresh exact "
        "target; consume suppressed and the durable claim remains active."
    )
    context.alerts.append(
        Alert(key=f"active-claim-mismatch:{attempt.attempt_id}", line=line),
    )
