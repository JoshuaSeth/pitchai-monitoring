# Copyright (c) 2026 PitchAI. All rights reserved.
"""Authoritative post-consume result persistence and requester alerts."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .guardian import Alert
from .models import utc_iso

if TYPE_CHECKING:
    from .models import AccountObservation, ConsumeResult, ResetCredit
    from .organization_claim import CoordinatedAttempt
    from .organization_policy import RedemptionSelection
    from .organization_runtime import OrganizationRunContext


SUCCESS_OUTCOMES = frozenset({"reset", "already_redeemed"})


@dataclass(frozen=True)
class ResultDisposition:
    """Derived status and alert inputs for one verified provider result."""

    success: bool
    status: str
    still_available: bool
    severity: str
    verification: str


class OrganizationResultRecorder:
    """Persist one provider result and derive its exact-credit verification."""

    _context: OrganizationRunContext

    def __init__(self, context: OrganizationRunContext) -> None:
        """Bind the scheduled run receiving the provider result."""
        self._context = context

    def complete(
        self,
        attempt: CoordinatedAttempt,
        selection: RedemptionSelection,
        result: ConsumeResult,
        post: AccountObservation,
    ) -> bool:
        """Finalize a provider result against the refreshed exact credit.

        Returns:
            True when the result requires an organization capacity refresh.
        """
        context = self._context
        credit = selection.credit
        post_credit = post.find_credit(credit.credit_ref)
        verification = credit_verification(post_credit, expected=credit)
        disposition = result_status(result, verification=verification)
        if disposition.severity == "error":
            context.summary.error_count += 1
        if disposition.success:
            context.summary.redemption_count += 1
        error_code = None if disposition.severity == "info" else verification
        details = {
            "pre_available_count": selection.observation.available_count,
            "post_available_count": post.available_count,
            "weekly_reset_at_before_consume": utc_iso(selection.weekly_reset_at),
            "expected_expires_at": utc_iso(credit.expires_at)
            if credit.expires_at
            else None,
            "post_expires_at": utc_iso(post_credit.expires_at)
            if post_credit and post_credit.expires_at
            else None,
        }
        context.audit.update_attempt(
            attempt_id=attempt.attempt_id,
            now=context.clock(),
            status=disposition.status,
            outcome=result.code,
            windows_reset=result.windows_reset,
            verification=verification,
            error_code=error_code,
            details=details,
        )
        context.claims.mark(
            attempt_id=attempt.attempt_id,
            state=disposition.status,
            now=context.clock(),
        )
        event_details = {
            **details,
            "outcome": result.code,
            "windows_reset": result.windows_reset,
            "verification": verification,
            "status": disposition.status,
        }
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="redemption_attempt_completed",
            severity=disposition.severity,
            account_ref=selection.observation.descriptor.account_ref,
            account_label=selection.observation.descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            attempt_id=attempt.attempt_id,
            details=event_details,
        )
        self.append_alert(attempt, selection, result, disposition)
        return disposition.success

    def append_alert(
        self,
        attempt: CoordinatedAttempt,
        selection: RedemptionSelection,
        result: ConsumeResult,
        disposition: ResultDisposition,
    ) -> None:
        """Queue one deduplicated requester-private result alert when needed."""
        observation = selection.observation
        credit = selection.credit
        if disposition.success:
            line = (
                f"SUCCESS {html.escape(observation.descriptor.label)} credit handled: "
                f"{result.code}, "
                f"{result.windows_reset} window(s) reset; attempt {attempt.attempt_id[:12]}. "
                f"Its weekly reset {html.escape(utc_iso(selection.weekly_reset_at))} was furthest "
                "among strictly >48h eligible accounts."
            )
            self._context.alerts.append(
                Alert(key=f"redemption-success:{attempt.attempt_id}", line=line),
            )
        elif (
            result.code == "nothing_to_reset"
            and disposition.still_available
            and credit.expires_at is not None
        ):
            key = (
                f"redemption-waiting:{observation.descriptor.account_ref}:"
                f"{credit.credit_ref}:{utc_iso(credit.expires_at)}:nothing_to_reset"
            )
            line = (
                f"WARNING {html.escape(observation.descriptor.label)} returned "
                "nothing_to_reset; the exact credit expiring "
                f"{html.escape(utc_iso(credit.expires_at))} remains available. "
                "A later pass will retry only if fresh organization exhaustion still holds."
            )
            self._context.alerts.append(Alert(key=key, line=line))
        elif disposition.severity == "error":
            line = (
                f"ERROR {html.escape(observation.descriptor.label)} returned "
                f"{result.code}, but exact-credit verification was "
                f"{disposition.verification}; attempt {attempt.attempt_id[:12]}."
            )
            self._context.alerts.append(
                Alert(key=f"redemption-invalid:{attempt.attempt_id}", line=line),
            )


def result_status(result: ConsumeResult, *, verification: str) -> ResultDisposition:
    """Map one provider outcome and exact-credit state to audit status.

    Returns:
        The success flag, durable status, exact-credit state, and alert severity.

    Raises:
        ValueError: The provider result code is unsupported.
    """
    still_available = verification == "exact_credit_still_available"
    verified_terminal = verification in {
        "exact_credit_absent",
        "exact_credit_not_redeemable",
    }
    if not verified_terminal and not still_available:
        return ResultDisposition(
            success=False,
            status="verification_failed",
            still_available=False,
            severity="error",
            verification=verification,
        )
    if result.code in SUCCESS_OUTCOMES:
        status = "verification_failed" if still_available else "succeeded"
    elif result.code == "no_credit":
        status = "failed" if still_available else "reconciled_absent"
    elif result.code == "nothing_to_reset":
        status = "completed" if still_available else "reconciled_absent"
    else:
        message = f"unsupported consume outcome: {result.code}"
        raise ValueError(message)
    success = verified_terminal
    severity = "error" if status in {"failed", "verification_failed"} else "info"
    return ResultDisposition(
        success=success,
        status=status,
        still_available=still_available,
        severity=severity,
        verification=verification,
    )


def credit_verification(
    post_credit: ResetCredit | None,
    *,
    expected: ResetCredit,
) -> str:
    """Describe the exact credit's authoritative post-consume identity.

    Returns:
        A stable verification code.
    """
    if post_credit is None:
        return "exact_credit_absent"
    if post_credit.expires_at != expected.expires_at:
        return "exact_credit_expiry_changed"
    if post_credit.is_redeemable:
        return "exact_credit_still_available"
    return "exact_credit_not_redeemable"
