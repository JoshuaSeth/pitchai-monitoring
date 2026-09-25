# Copyright (c) 2026 PitchAI. All rights reserved.
"""Finalize guardian redemption attempts from verified provider results."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from .guardian_types import Alert
from .models import utc_iso

if TYPE_CHECKING:
    from .guardian_types import AttemptCompletion, GuardianDependencies


def complete_attempt(
    dependencies: GuardianDependencies,
    completion: AttemptCompletion,
) -> None:
    """Persist a verified attempt result and append its outcome alert."""
    request = completion.request
    context = request.context
    success, status = _completion_status(
        completion.result.code,
        still_available=completion.still_available,
    )
    verification = "exact_credit_still_available" if completion.still_available else "exact_credit_absent"
    severity = "error" if status in {"failed", "verification_failed"} else "info"
    if severity == "error":
        context.summary.error_count += 1
    if success:
        context.summary.redemption_count += 1
    dependencies.audit.update_attempt(
        attempt_id=completion.attempt.attempt_id,
        now=dependencies.clock(),
        status=status,
        outcome=completion.result.code,
        windows_reset=completion.result.windows_reset,
        verification=verification,
        error_code=None if severity == "info" else "credit_remained_available",
        details={
            "pre_available_count": request.observation.available_count,
            "post_available_count": completion.post.available_count,
        },
    )
    dependencies.audit.record_event(
        run_id=context.run_id,
        now=dependencies.clock(),
        event_type="redemption_attempt_completed",
        severity=severity,
        account_ref=request.observation.descriptor.account_ref,
        account_label=request.observation.descriptor.label,
        credit_ref=request.credit.credit_ref,
        expires_at=request.credit.expires_at,
        attempt_id=completion.attempt.attempt_id,
        details={
            "outcome": completion.result.code,
            "windows_reset": completion.result.windows_reset,
            "verification": verification,
            "status": status,
            "pre_available_count": request.observation.available_count,
            "post_available_count": completion.post.available_count,
        },
    )
    _append_completion_alert(completion, success=success, severity=severity)


def _completion_status(result_code: str, *, still_available: bool) -> tuple[bool, str]:
    success = False
    status = "completed"
    if result_code in {"reset", "already_redeemed"}:
        success = not still_available
        status = "succeeded" if success else "verification_failed"
    elif result_code == "no_credit":
        success = not still_available
        status = "reconciled_absent" if success else "failed"
    elif result_code == "nothing_to_reset":
        success = not still_available
        status = "reconciled_absent" if success else "completed"
    return success, status


def _append_completion_alert(
    completion: AttemptCompletion,
    *,
    success: bool,
    severity: str,
) -> None:
    request = completion.request
    context = request.context
    label = html.escape(request.observation.descriptor.label)
    attempt_ref = completion.attempt.attempt_id[:12]
    if success:
        context.alerts.append(
            Alert(
                key=f"redemption-success:{completion.attempt.attempt_id}",
                line=(
                    f"SUCCESS {label} credit handled: {completion.result.code}, "
                    f"{completion.result.windows_reset} window(s) reset, exact credit absent "
                    f"after verification; attempt {attempt_ref}."
                ),
            ),
        )
        return
    if completion.result.code == "nothing_to_reset" and completion.still_available:
        _append_waiting_alert(completion, label)
        return
    if severity == "error":
        context.alerts.append(
            Alert(
                key=f"redemption-invalid:{completion.attempt.attempt_id}",
                line=(
                    f"ERROR {label} returned {completion.result.code}, but the exact credit "
                    f"remained available; attempt {attempt_ref}."
                ),
            ),
        )


def _append_waiting_alert(completion: AttemptCompletion, label: str) -> None:
    request = completion.request
    expires_at = request.credit.expires_at
    if expires_at is None:
        msg = "redemption follow-up requires an expiring credit"
        raise RuntimeError(msg)
    request.context.alerts.append(
        Alert(
            key=(
                f"redemption-waiting:{request.observation.descriptor.account_ref}:"
                f"{request.credit.credit_ref}:{utc_iso(expires_at)}:nothing_to_reset"
            ),
            line=(
                f"WARNING {label} provider returned nothing_to_reset; the exact credit expiring "
                f"{html.escape(utc_iso(expires_at))} remains available. "
                "Automatic retries continue every 15 minutes."
            ),
        ),
    )
