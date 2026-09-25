# Copyright (c) 2026 PitchAI. All rights reserved.
"""Execute exact guardian redemptions and verify fresh post-state."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from .clients import RemoteCallError
from .guardian_completion import complete_attempt
from .guardian_notifications import safe_error_code
from .guardian_types import (
    Alert,
    AttemptCompletion,
)

if TYPE_CHECKING:
    from .audit import RedemptionAttempt
    from .guardian_types import (
        AttemptRequest,
        GuardianDependencies,
    )
    from .models import AccountObservation, ConsumeResult


def execute_attempt(
    dependencies: GuardianDependencies,
    request: AttemptRequest,
) -> None:
    """Consume one exact credit and verify it against fresh post-state."""
    context = request.context
    attempt = dependencies.audit.start_or_resume_attempt(
        run_id=context.run_id,
        now=dependencies.clock(),
        observation=request.observation,
        credit=request.credit,
        reason=request.reason,
    )
    context.summary.redemption_attempt_count += 1
    dependencies.audit.record_event(
        run_id=context.run_id,
        now=dependencies.clock(),
        event_type="redemption_attempt_started",
        account_ref=request.observation.descriptor.account_ref,
        account_label=request.observation.descriptor.label,
        credit_ref=request.credit.credit_ref,
        expires_at=request.credit.expires_at,
        attempt_id=attempt.attempt_id,
        details={"reason": request.reason, "resumed": attempt.resumed},
    )
    try:
        result = dependencies.source.consume_credit(
            request.observation,
            request.credit,
            attempt.idempotency_key,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        _record_attempt_failure(dependencies, request, attempt, exc)
        return
    try:
        post = _refresh_and_record_post_state(dependencies, request)
    except (RuntimeError, ValueError, OSError) as exc:
        _record_verification_failure(dependencies, request, attempt, result, exc)
        return
    post_credit = post.find_credit(request.credit.credit_ref)
    still_available = post_credit is not None and post_credit.is_redeemable
    complete_attempt(
        dependencies,
        AttemptCompletion(
            request=request,
            attempt=attempt,
            result=result,
            post=post,
            still_available=still_available,
        ),
    )


def _refresh_and_record_post_state(
    dependencies: GuardianDependencies,
    request: AttemptRequest,
) -> AccountObservation:
    post = dependencies.source.refresh_account(request.observation.descriptor)
    dependencies.audit.record_snapshot(
        run_id=request.context.run_id,
        phase="post_redemption_verification",
        observation=post,
    )
    return post


def _record_attempt_failure(
    dependencies: GuardianDependencies,
    request: AttemptRequest,
    attempt: RedemptionAttempt,
    error: Exception,
) -> None:
    error_code = safe_error_code(error)
    uncertain = isinstance(error, RemoteCallError) and error.ambiguous
    dependencies.audit.update_attempt(
        attempt_id=attempt.attempt_id,
        now=dependencies.clock(),
        status="uncertain" if uncertain else "failed",
        error_code=error_code,
        details={"transport_ambiguous": uncertain},
    )
    dependencies.audit.record_event(
        run_id=request.context.run_id,
        now=dependencies.clock(),
        event_type="redemption_attempt_failed",
        severity="error",
        account_ref=request.observation.descriptor.account_ref,
        account_label=request.observation.descriptor.label,
        credit_ref=request.credit.credit_ref,
        expires_at=request.credit.expires_at,
        attempt_id=attempt.attempt_id,
        details={"error_code": error_code, "transport_ambiguous": uncertain},
    )
    request.context.summary.error_count += 1
    label = html.escape(request.observation.descriptor.label)
    request.context.alerts.append(
        Alert(
            key=f"attempt-error:{attempt.attempt_id}:{error_code}",
            line=(f"ERROR {label} redemption attempt failed ({error_code}); audit attempt {attempt.attempt_id[:12]}."),
        ),
    )


def _record_verification_failure(
    dependencies: GuardianDependencies,
    request: AttemptRequest,
    attempt: RedemptionAttempt,
    result: ConsumeResult,
    error: Exception,
) -> None:
    error_code = safe_error_code(error)
    dependencies.audit.update_attempt(
        attempt_id=attempt.attempt_id,
        now=dependencies.clock(),
        status="verification_failed",
        outcome=result.code,
        windows_reset=result.windows_reset,
        verification="post_state_unavailable",
        error_code=error_code,
    )
    dependencies.audit.record_event(
        run_id=request.context.run_id,
        now=dependencies.clock(),
        event_type="redemption_verification_failed",
        severity="error",
        account_ref=request.observation.descriptor.account_ref,
        account_label=request.observation.descriptor.label,
        credit_ref=request.credit.credit_ref,
        expires_at=request.credit.expires_at,
        attempt_id=attempt.attempt_id,
        details={"outcome": result.code, "error_code": error_code},
    )
    request.context.summary.error_count += 1
    label = html.escape(request.observation.descriptor.label)
    request.context.alerts.append(
        Alert(
            key=f"verification-error:{attempt.attempt_id}",
            line=(
                f"ERROR {label} returned {result.code}, but the post-state check failed; "
                f"attempt {attempt.attempt_id[:12]}."
            ),
        ),
    )
