# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scan guardian accounts and route expiring credits to safe decisions."""

from __future__ import annotations

import html
from datetime import timedelta
from typing import TYPE_CHECKING

from .clients import AccountScanError
from .guardian_notifications import safe_error_code
from .guardian_recheck import recheck_and_redeem
from .guardian_reconciliation import reconcile_pending_attempts
from .guardian_types import (
    AUTO_REDEEM_HORIZON,
    Alert,
    CreditDecision,
    RecheckRequest,
)
from .guardian_warnings import record_warnings
from .models import utc_iso

if TYPE_CHECKING:
    from .guardian_types import (
        GuardianDependencies,
        ScanRequest,
    )
    from .models import AccountObservation, ResetCredit


def scan_account(
    dependencies: GuardianDependencies,
    request: ScanRequest,
) -> None:
    """Scan one account, reconcile state, and process safe redemption candidates."""
    try:
        observation = dependencies.source.refresh_account(request.descriptor)
    except (RuntimeError, ValueError, OSError) as exc:
        _record_scan_failure(dependencies, request, exc)
        return
    context = request.context
    context.summary.scanned_account_count += 1
    context.summary.credit_count += len(observation.credits)
    dependencies.audit.record_snapshot(
        run_id=context.run_id,
        phase="inventory",
        observation=observation,
    )
    reconcile_pending_attempts(dependencies, context, observation)
    candidates: list[ResetCredit] = [
        credit for credit in observation.credits if _evaluate_credit(dependencies, request, observation, credit)
    ]
    for candidate in candidates:
        recheck_and_redeem(
            dependencies,
            RecheckRequest(
                context=context,
                descriptor=request.descriptor,
                expected=candidate,
                reason="automatic_within_two_hours",
                enforce_horizon=True,
            ),
        )


def _record_scan_failure(
    dependencies: GuardianDependencies,
    request: ScanRequest,
    error: Exception,
) -> None:
    error_code = safe_error_code(error)
    request.context.summary.error_count += 1
    broker_state = error.broker_state if isinstance(error, AccountScanError) else {}
    dependencies.audit.record_event(
        run_id=request.context.run_id,
        now=dependencies.clock(),
        event_type="account_scan_failed",
        severity="error",
        account_ref=request.descriptor.account_ref,
        account_label=request.descriptor.label,
        details={"error_code": error_code, "broker_state": broker_state},
    )
    day = dependencies.clock().date().isoformat()
    request.context.alerts.append(
        Alert(
            key=f"account-error:{request.descriptor.account_ref}:{error_code}:{day}",
            line=(f"ERROR {html.escape(request.descriptor.label)} could not be checked ({error_code})."),
        ),
    )


def _evaluate_credit(
    dependencies: GuardianDependencies,
    request: ScanRequest,
    observation: AccountObservation,
    credit: ResetCredit,
) -> bool:
    context = request.context
    dependencies.audit.record_event(
        run_id=context.run_id,
        now=dependencies.clock(),
        event_type="credit_observed",
        account_ref=request.descriptor.account_ref,
        account_label=request.descriptor.label,
        credit_ref=credit.credit_ref,
        expires_at=credit.expires_at,
        details=credit.sanitized(),
    )
    if not credit.is_redeemable:
        dependencies.audit.record_event(
            run_id=context.run_id,
            now=dependencies.clock(),
            event_type="credit_not_redeemable",
            severity="warning",
            account_ref=request.descriptor.account_ref,
            account_label=request.descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            details={
                "status": credit.status,
                "reset_type": credit.reset_type,
                "supported_by_plan": credit.supported_by_plan,
            },
        )
        return False
    context.summary.redeemable_credit_count += 1
    if credit.expires_at is None:
        msg = "redeemable credit is missing an expiry"
        raise RuntimeError(msg)
    remaining = credit.expires_at - dependencies.clock()
    if remaining <= timedelta(0):
        _record_expired_credit(dependencies, request, credit, remaining)
        return False
    warning_emitted = record_warnings(
        dependencies,
        CreditDecision(
            context=context,
            observation=observation,
            credit=credit,
            remaining=remaining,
        ),
    )
    within_horizon = remaining <= AUTO_REDEEM_HORIZON
    dependencies.audit.record_event(
        run_id=context.run_id,
        now=dependencies.clock(),
        event_type="credit_decision",
        account_ref=request.descriptor.account_ref,
        account_label=request.descriptor.label,
        credit_ref=credit.credit_ref,
        expires_at=credit.expires_at,
        details={
            "decision": "recheck_for_redemption" if within_horizon else "wait",
            "remaining_seconds": int(remaining.total_seconds()),
            "new_warning_emitted": warning_emitted,
        },
    )
    return within_horizon


def _record_expired_credit(
    dependencies: GuardianDependencies,
    request: ScanRequest,
    credit: ResetCredit,
    remaining: timedelta,
) -> None:
    expires_at = credit.expires_at
    if expires_at is None:
        msg = "expired-credit records require an expiry"
        raise RuntimeError(msg)
    request.context.summary.error_count += 1
    dependencies.audit.record_event(
        run_id=request.context.run_id,
        now=dependencies.clock(),
        event_type="credit_expired_unprotected",
        severity="error",
        account_ref=request.descriptor.account_ref,
        account_label=request.descriptor.label,
        credit_ref=credit.credit_ref,
        expires_at=expires_at,
        details={"observed_seconds_after_expiry": int(-remaining.total_seconds())},
    )
    request.context.alerts.append(
        Alert(
            key=(f"expired:{request.descriptor.account_ref}:{credit.credit_ref}:{utc_iso(expires_at)}"),
            line=(
                f"ERROR {html.escape(request.descriptor.label)} credit was still listed after "
                f"expiry {html.escape(utc_iso(expires_at))}."
            ),
        ),
    )
