# Copyright (c) 2026 PitchAI. All rights reserved.
"""Post-redemption organization-capacity verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .guardian import Alert
from .organization_policy import evaluate_organization
from .organization_refresh import refresh_organization
from .organization_reporting import (
    record_organization_decision,
    sanitized_decision,
)

if TYPE_CHECKING:
    from .organization_runtime import OrganizationRunContext


def verify_restored_capacity(context: OrganizationRunContext) -> None:
    """Require a full fresh refresh to prove usable capacity returned."""
    inventory = refresh_organization(
        context,
        phase="post_redemption_organization_refresh",
    )
    decision = evaluate_organization(
        descriptors=inventory.descriptors,
        observations=inventory.observations,
        failed_account_refs=inventory.failed_account_refs,
        now=context.clock(),
    )
    record_organization_decision(
        context,
        decision,
        phase="post_redemption_verification",
    )
    if decision.state == "not_exhausted":
        return
    context.summary.error_count += 1
    context.audit.record_event(
        run_id=context.run_id,
        now=context.clock(),
        event_type="post_redemption_capacity_not_restored",
        severity="error",
        details=dict(sanitized_decision(decision, now=context.clock())),
    )
    line = "ERROR one credit was handled, but fresh organization capacity was not proven usable."
    context.alerts.append(
        Alert(
            key=f"post-redemption-capacity-not-restored:{context.run_id}",
            line=line,
        ),
    )
