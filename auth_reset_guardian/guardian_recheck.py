# Copyright (c) 2026 PitchAI. All rights reserved.
"""Perform the mandatory fresh pre-redemption guardian recheck."""

from __future__ import annotations

import html
from datetime import timedelta
from typing import TYPE_CHECKING

from .guardian_attempts import execute_attempt
from .guardian_notifications import safe_error_code
from .guardian_types import (
    AUTO_REDEEM_HORIZON,
    Alert,
    AttemptRequest,
)
from .models import utc_iso

if TYPE_CHECKING:
    from .guardian_types import (
        GuardianDependencies,
        RecheckRequest,
    )
    from .models import AccountObservation, ResetCredit


def recheck_and_redeem(
    dependencies: GuardianDependencies,
    request: RecheckRequest,
) -> None:
    """Require fresh exact-credit state before any consume request.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    expected_expiry = request.expected.expires_at
    if expected_expiry is None:
        msg = "redemption rechecks require an expiring credit"
        raise RuntimeError(msg)
    try:
        fresh = _refresh_and_record_recheck(dependencies, request)
    except (RuntimeError, ValueError, OSError) as exc:
        _record_recheck_failure(dependencies, request, exc)
        return
    exact = fresh.find_credit(request.expected.credit_ref)
    if exact is None or not exact.is_redeemable:
        _record_absent_skip(dependencies, request, fresh)
        return
    if exact.expires_at is None:
        msg = "redemption attempts require an expiring credit"
        raise RuntimeError(msg)
    if exact.expires_at != expected_expiry:
        _record_expiry_mismatch(dependencies, request, exact)
        return
    remaining = exact.expires_at - dependencies.clock()
    if remaining <= timedelta(0):
        request.context.summary.error_count += 1
        dependencies.audit.record_event(
            run_id=request.context.run_id,
            now=dependencies.clock(),
            event_type="redemption_skipped_expired",
            severity="error",
            account_ref=request.descriptor.account_ref,
            account_label=request.descriptor.label,
            credit_ref=exact.credit_ref,
            expires_at=exact.expires_at,
            details={"remaining_seconds": int(remaining.total_seconds())},
        )
        return
    if request.enforce_horizon and remaining > AUTO_REDEEM_HORIZON:
        dependencies.audit.record_event(
            run_id=request.context.run_id,
            now=dependencies.clock(),
            event_type="redemption_skipped_outside_horizon",
            account_ref=request.descriptor.account_ref,
            account_label=request.descriptor.label,
            credit_ref=exact.credit_ref,
            expires_at=exact.expires_at,
            details={"remaining_seconds": int(remaining.total_seconds())},
        )
        return
    if request.context.dry_run:
        dependencies.audit.record_event(
            run_id=request.context.run_id,
            now=dependencies.clock(),
            event_type="redemption_suppressed_dry_run",
            account_ref=request.descriptor.account_ref,
            account_label=request.descriptor.label,
            credit_ref=exact.credit_ref,
            expires_at=exact.expires_at,
            details={"reason": request.reason, "fresh_recheck_completed": True},
        )
        return
    execute_attempt(
        dependencies,
        AttemptRequest(
            context=request.context,
            observation=fresh,
            credit=exact,
            reason=request.reason,
        ),
    )


def _refresh_and_record_recheck(
    dependencies: GuardianDependencies,
    request: RecheckRequest,
) -> AccountObservation:
    fresh = dependencies.source.refresh_account(request.descriptor)
    dependencies.audit.record_snapshot(
        run_id=request.context.run_id,
        phase="pre_redemption_recheck",
        observation=fresh,
    )
    return fresh


def _record_recheck_failure(
    dependencies: GuardianDependencies,
    request: RecheckRequest,
    error: Exception,
) -> None:
    summary = request.context.summary
    summary.error_count += 1
    error_code = safe_error_code(error)
    dependencies.audit.record_event(
        run_id=request.context.run_id,
        now=dependencies.clock(),
        event_type="redemption_recheck_failed",
        severity="error",
        account_ref=request.descriptor.account_ref,
        account_label=request.descriptor.label,
        credit_ref=request.expected.credit_ref,
        expires_at=request.expected.expires_at,
        details={"error_code": error_code, "reason": request.reason},
    )
    expected_expiry = request.expected.expires_at
    if expected_expiry is None:
        msg = "redemption recheck alerts require an expiring credit"
        raise RuntimeError(msg)
    request.context.alerts.append(
        Alert(
            key=(
                f"recheck-error:{request.descriptor.account_ref}:"
                f"{request.expected.credit_ref}:{utc_iso(expected_expiry)}:{error_code}"
            ),
            line=(f"ERROR {html.escape(request.descriptor.label)} fresh redemption recheck failed."),
        ),
    )


def _record_absent_skip(
    dependencies: GuardianDependencies,
    request: RecheckRequest,
    fresh: AccountObservation,
) -> None:
    dependencies.audit.record_event(
        run_id=request.context.run_id,
        now=dependencies.clock(),
        event_type="redemption_skipped_after_fresh_recheck",
        account_ref=request.descriptor.account_ref,
        account_label=request.descriptor.label,
        credit_ref=request.expected.credit_ref,
        expires_at=request.expected.expires_at,
        details={
            "reason": "exact_credit_absent_or_not_redeemable",
            "fresh_available_count": fresh.available_count,
        },
    )


def _record_expiry_mismatch(
    dependencies: GuardianDependencies,
    request: RecheckRequest,
    exact: ResetCredit,
) -> None:
    expected_expiry = request.expected.expires_at
    exact_expiry = exact.expires_at
    if expected_expiry is None or exact_expiry is None:
        msg = "expiry mismatch records require both credit expiries"
        raise RuntimeError(msg)
    summary = request.context.summary
    summary.error_count += 1
    dependencies.audit.record_event(
        run_id=request.context.run_id,
        now=dependencies.clock(),
        event_type="redemption_skipped_expiry_mismatch",
        severity="error",
        account_ref=request.descriptor.account_ref,
        account_label=request.descriptor.label,
        credit_ref=request.expected.credit_ref,
        expires_at=expected_expiry,
        details={
            "reason": "exact_credit_expiry_changed_on_fresh_recheck",
            "expected_expires_at": utc_iso(expected_expiry),
            "fresh_expires_at": utc_iso(exact_expiry),
        },
    )
    request.context.alerts.append(
        Alert(
            key=(
                f"expiry-mismatch:{request.descriptor.account_ref}:"
                f"{request.expected.credit_ref}:{utc_iso(expected_expiry)}:"
                f"{utc_iso(exact_expiry)}"
            ),
            line=(
                f"ERROR {html.escape(request.descriptor.label)} exact credit expiry changed "
                "during the fresh redemption recheck; no consume was attempted."
            ),
        ),
    )
