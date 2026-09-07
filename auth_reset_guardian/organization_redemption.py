# Copyright (c) 2026 PitchAI. All rights reserved.
"""One targeted, durable organization reset redemption and verification."""

from __future__ import annotations

import html
from functools import partial
from typing import TYPE_CHECKING, cast

from .clients import RemoteCallError
from .guardian import Alert
from .models import utc_iso
from .organization_io import capture_io, safe_error_code
from .organization_result import OrganizationResultRecorder

if TYPE_CHECKING:
    from .models import AccountObservation, ConsumeResult
    from .organization_claim import CoordinatedAttempt
    from .organization_policy import RedemptionSelection
    from .organization_runtime import OrganizationRunContext


class OrganizationRedemption:
    """Execute and reconcile the only provider mutation allowed by the policy."""

    _context: OrganizationRunContext

    def __init__(self, context: OrganizationRunContext) -> None:
        """Bind one scheduled run's source, audit, and claim state."""
        self._context = context

    def execute(
        self,
        attempt: CoordinatedAttempt,
        selection: RedemptionSelection,
    ) -> bool:
        """Consume one exact credit and persist its authoritative post-state.

        Returns:
            True when the result requires an organization capacity refresh.

        Raises:
            RuntimeError: An IO capture violates its value-or-error invariant.
        """
        context = self._context
        observation = selection.observation
        credit = selection.credit
        context.summary.redemption_attempt_count += 1
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="redemption_attempt_started",
            account_ref=observation.descriptor.account_ref,
            account_label=observation.descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            attempt_id=attempt.attempt_id,
            details={
                "reason": "automatic_organization_exhaustion",
                "resumed": attempt.resumed,
                "weekly_reset_at": utc_iso(selection.weekly_reset_at),
            },
        )
        consume = partial(
            context.source.consume_credit,
            observation,
            credit,
            attempt.idempotency_key,
        )
        consumed = capture_io(consume)
        if consumed.error is not None:
            self.record_consume_failure(attempt, selection, consumed.error)
            return False
        raw_result = consumed.value
        if raw_result is None:
            message = "consume call returned neither a result nor an error"
            raise RuntimeError(message)
        result = cast("ConsumeResult", raw_result)
        refresh = partial(context.source.refresh_account, observation.descriptor)
        refreshed = capture_io(refresh)
        if refreshed.error is not None:
            self.record_verification_failure(
                attempt,
                selection,
                result,
                refreshed.error,
            )
            return False
        raw_post = refreshed.value
        if raw_post is None:
            message = "post-consume refresh returned neither a result nor an error"
            raise RuntimeError(message)
        post = cast("AccountObservation", raw_post)
        context.audit.record_snapshot(
            run_id=context.run_id,
            phase="post_redemption_verification",
            observation=post,
        )
        return OrganizationResultRecorder(context).complete(
            attempt,
            selection,
            result,
            post,
        )

    def record_consume_failure(
        self,
        attempt: CoordinatedAttempt,
        selection: RedemptionSelection,
        error: BaseException,
    ) -> None:
        """Persist a definite or transport-ambiguous consume failure."""
        context = self._context
        ambiguous = isinstance(error, RemoteCallError) and error.ambiguous
        status = "uncertain" if ambiguous else "failed"
        error_code = safe_error_code(error)
        context.audit.update_attempt(
            attempt_id=attempt.attempt_id,
            now=context.clock(),
            status=status,
            error_code=error_code,
            details={"transport_ambiguous": ambiguous},
        )
        context.claims.mark(
            attempt_id=attempt.attempt_id,
            state=status,
            now=context.clock(),
        )
        observation = selection.observation
        credit = selection.credit
        context.summary.error_count += 1
        context.audit.record_event(
            event_type="redemption_attempt_failed",
            severity="error",
            run_id=context.run_id,
            now=context.clock(),
            account_ref=observation.descriptor.account_ref,
            account_label=observation.descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            attempt_id=attempt.attempt_id,
            details={"error_code": error_code, "transport_ambiguous": ambiguous},
        )
        line = (
            f"ERROR {html.escape(observation.descriptor.label)} redemption attempt "
            f"failed ({error_code}); "
            f"audit attempt {attempt.attempt_id[:12]}."
        )
        context.alerts.append(
            Alert(key=f"attempt-error:{attempt.attempt_id}:{error_code}", line=line),
        )

    def record_verification_failure(
        self,
        attempt: CoordinatedAttempt,
        selection: RedemptionSelection,
        result: ConsumeResult,
        error: BaseException,
    ) -> None:
        """Persist a consume result whose authoritative refresh failed."""
        context = self._context
        error_code = safe_error_code(error)
        context.audit.update_attempt(
            attempt_id=attempt.attempt_id,
            now=context.clock(),
            status="verification_failed",
            outcome=result.code,
            windows_reset=result.windows_reset,
            verification="post_state_unavailable",
            error_code=error_code,
        )
        context.claims.mark(
            attempt_id=attempt.attempt_id,
            state="verification_failed",
            now=context.clock(),
        )
        observation = selection.observation
        credit = selection.credit
        context.summary.error_count += 1
        context.audit.record_event(
            event_type="redemption_verification_failed",
            severity="error",
            run_id=context.run_id,
            now=context.clock(),
            account_ref=observation.descriptor.account_ref,
            account_label=observation.descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            attempt_id=attempt.attempt_id,
            details={"outcome": result.code, "error_code": error_code},
        )
        line = (
            f"ERROR {html.escape(observation.descriptor.label)} returned {result.code}, "
            "but the post-state check failed; "
            f"attempt {attempt.attempt_id[:12]}."
        )
        context.alerts.append(
            Alert(key=f"verification-error:{attempt.attempt_id}", line=line),
        )
