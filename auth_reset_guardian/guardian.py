# Copyright (c) 2026 PitchAI. All rights reserved.
"""Coordinate safe reset-credit observation, warning, and redemption."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .command_notifier import CommandNotifier, NotificationError
from .guardian_notifications import (
    alert_batches,
    safe_error_code,
    send_alerts,
)
from .guardian_recheck import recheck_and_redeem
from .guardian_scan import scan_account
from .guardian_types import (
    Alert,
    GuardianDependencies,
    GuardianRunSummary,
    RecheckRequest,
    RunContext,
    ScanRequest,
)
from .model_values import utc_now
from .models import PayloadError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from .audit import AuditStore
    from .clients import GuardianSource
    from .guardian_types import Notifier

__all__ = [
    "Alert",
    "CommandNotifier",
    "Guardian",
    "GuardianRunSummary",
    "NotificationError",
    "alert_batches",
]


class Guardian:
    """Coordinate guardian boundaries while focused modules own each operation."""

    def __init__(
        self,
        *,
        source: GuardianSource,
        audit: AuditStore,
        notifier: Notifier | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        """Initialize guardian dependencies."""
        self._dependencies: GuardianDependencies = GuardianDependencies(
            source=source,
            audit=audit,
            notifier=notifier,
            clock=clock,
        )

    def run(self, *, mode: str, dry_run: bool) -> GuardianRunSummary:
        """Scan every account and safely process expiring credits.

        Returns:
            The resulting value.

        """
        dependencies = self._dependencies
        run_id = dependencies.audit.start_run(mode=mode, now=dependencies.clock())
        summary = GuardianRunSummary(run_id=run_id, mode=mode)
        context = RunContext(
            run_id=run_id,
            mode=mode,
            dry_run=dry_run,
            summary=summary,
            alerts=[],
        )
        try:
            descriptors = dependencies.source.list_accounts()
        except (RuntimeError, ValueError, OSError) as exc:
            _finish_failed_inventory(dependencies, context, exc)
            return summary
        summary.account_count = len(descriptors)
        if not descriptors:
            summary.error_count += 1
            summary.status = "failed"
            dependencies.audit.record_event(
                run_id=run_id,
                now=dependencies.clock(),
                event_type="account_inventory_empty",
                severity="error",
                details={},
            )
        for descriptor in descriptors:
            scan_account(
                dependencies,
                ScanRequest(context=context, descriptor=descriptor),
            )
        _set_run_status(summary)
        if dependencies.notifier is not None and context.alerts:
            send_alerts(
                dependencies,
                run_id=run_id,
                summary=summary,
                alerts=context.alerts,
            )
            if summary.error_count and summary.status == "ok":
                summary.status = "degraded"
        _finish_run(dependencies, summary)
        return summary

    def manual_redeem(
        self,
        *,
        account_label: str,
        expires_at: datetime,
        reason: str,
        dry_run: bool,
    ) -> GuardianRunSummary:
        """Redeem one exact account and expiry after the normal fresh recheck.

        Returns:
            The resulting value.

        """
        dependencies = self._dependencies
        mode = "manual_dry_run" if dry_run else "manual"
        run_id = dependencies.audit.start_run(mode=mode, now=dependencies.clock())
        summary = GuardianRunSummary(run_id=run_id, mode=mode)
        context = RunContext(
            run_id=run_id,
            mode=mode,
            dry_run=dry_run,
            summary=summary,
            alerts=[],
        )
        try:
            _perform_manual_operation(
                dependencies,
                context,
                account_label,
                expires_at,
                reason,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            summary.error_count += 1
            dependencies.audit.record_event(
                run_id=run_id,
                now=dependencies.clock(),
                event_type="manual_redemption_failed",
                severity="error",
                account_label=account_label,
                expires_at=expires_at,
                details={"error_code": safe_error_code(exc), "reason": reason[:240]},
            )
        summary.status = "degraded" if summary.error_count else "ok"
        if dependencies.notifier is not None and context.alerts:
            send_alerts(
                dependencies,
                run_id=run_id,
                summary=summary,
                alerts=context.alerts,
            )
        _finish_run(dependencies, summary)
        return summary


def _finish_failed_inventory(
    dependencies: GuardianDependencies,
    context: RunContext,
    error: Exception,
) -> None:
    summary = context.summary
    summary.error_count += 1
    summary.status = "failed"
    dependencies.audit.record_event(
        run_id=context.run_id,
        now=dependencies.clock(),
        event_type="account_inventory_failed",
        severity="error",
        details={"error_code": safe_error_code(error)},
    )
    _finish_run(dependencies, summary)


def _set_run_status(summary: GuardianRunSummary) -> None:
    if summary.account_count > 0 and summary.scanned_account_count == 0:
        summary.status = "failed"
    elif summary.error_count:
        summary.status = "degraded"
    elif summary.status == "running":
        summary.status = "ok"


def _finish_run(
    dependencies: GuardianDependencies,
    summary: GuardianRunSummary,
) -> None:
    dependencies.audit.finish_run(
        run_id=summary.run_id,
        now=dependencies.clock(),
        status=summary.status,
        summary=summary.serialized(),
    )


def _perform_manual_operation(
    dependencies: GuardianDependencies,
    context: RunContext,
    account_label: str,
    expires_at: datetime,
    reason: str,
) -> None:
    source_accounts = dependencies.source.list_accounts()
    matches = [
        descriptor for descriptor in source_accounts if descriptor.label == account_label
    ]
    context.summary.account_count = len(matches)
    if len(matches) != 1:
        msg = "manual redemption requires one exact account-label match"
        raise PayloadError(msg)
    initial = dependencies.source.refresh_account(matches[0])
    context.summary.scanned_account_count = 1
    context.summary.credit_count = len(initial.credits)
    dependencies.audit.record_snapshot(
        run_id=context.run_id,
        phase="manual_inventory",
        observation=initial,
    )
    expiry_matches = [
        credit for credit in initial.credits if credit.expires_at == expires_at
    ]
    matching = [credit for credit in expiry_matches if credit.is_redeemable]
    if len(matching) != 1:
        msg = "manual redemption requires one exact redeemable expiry match"
        raise PayloadError(msg)
    recheck_and_redeem(
        dependencies,
        RecheckRequest(
            context=context,
            descriptor=matches[0],
            expected=matching[0],
            reason=reason,
            enforce_horizon=False,
        ),
    )
