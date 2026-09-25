# Copyright (c) 2026 PitchAI. All rights reserved.
"""Evaluate and durably claim guardian expiry warnings."""

from __future__ import annotations

import html
from datetime import timedelta
from typing import TYPE_CHECKING

from .guardian_types import (
    WARNING_THRESHOLDS_HOURS,
    Alert,
)
from .models import utc_iso

if TYPE_CHECKING:
    from .guardian_types import (
        CreditDecision,
        GuardianDependencies,
    )


def record_warnings(
    dependencies: GuardianDependencies,
    decision: CreditDecision,
) -> bool:
    """Record newly crossed thresholds and reconstruct due live alerts.

    Returns:
        Whether the operation satisfied its contract.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    emitted = False
    credit = decision.credit
    context = decision.context
    observation = decision.observation
    if credit.expires_at is None:
        msg = "expiry warnings require an expiring credit"
        raise RuntimeError(msg)
    for threshold_hours in WARNING_THRESHOLDS_HOURS:
        if decision.remaining > timedelta(hours=threshold_hours):
            continue
        alert = _warning_alert(decision, threshold_hours)
        claimed = dependencies.audit.claim_warning(
            run_id=context.run_id,
            mode=context.mode,
            now=dependencies.clock(),
            account_ref=observation.descriptor.account_ref,
            credit=credit,
            threshold_hours=threshold_hours,
        )
        if claimed:
            emitted = True
            context.summary.warning_count += 1
            _record_claimed_warning(dependencies, decision, threshold_hours)
        if context.mode == "live":
            context.alerts.append(alert)
    return emitted


def _warning_alert(decision: CreditDecision, threshold_hours: int) -> Alert:
    credit = decision.credit
    observation = decision.observation
    if credit.expires_at is None:
        msg = "warning alerts require an expiring credit"
        raise RuntimeError(msg)
    return Alert(
        key=(
            f"warning:{observation.descriptor.account_ref}:{credit.credit_ref}:"
            f"{utc_iso(credit.expires_at)}:{threshold_hours}h"
        ),
        line=(
            f"WARNING {html.escape(observation.descriptor.label)} credit reaches the "
            f"{threshold_hours}h threshold; expires "
            f"{html.escape(utc_iso(credit.expires_at))}."
        ),
    )


def _record_claimed_warning(
    dependencies: GuardianDependencies,
    decision: CreditDecision,
    threshold_hours: int,
) -> None:
    observation = decision.observation
    credit = decision.credit
    late_by = max(
        0,
        int(
            timedelta(hours=threshold_hours).total_seconds() - decision.remaining.total_seconds(),
        ),
    )
    dependencies.audit.record_event(
        run_id=decision.context.run_id,
        now=dependencies.clock(),
        event_type="expiry_warning",
        severity="warning",
        account_ref=observation.descriptor.account_ref,
        account_label=observation.descriptor.label,
        credit_ref=credit.credit_ref,
        expires_at=credit.expires_at,
        threshold_hours=threshold_hours,
        details={
            "remaining_seconds": int(decision.remaining.total_seconds()),
            "late_by_seconds": late_by,
            "usage_state": observation.usage_state,
        },
    )
