from __future__ import annotations

import html
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Sequence

from .audit import AuditStore, RedemptionAttempt
from .clients import AccountScanError, GuardianSource, RemoteCallError
from .models import (
    AccountDescriptor,
    AccountObservation,
    ConsumeResult,
    PayloadError,
    ResetCredit,
    parse_timestamp,
    utc_iso,
    utc_now,
)


WARNING_THRESHOLDS_HOURS = (48, 24, 6, 2, 1)
AUTO_REDEEM_HORIZON = timedelta(hours=2)


@dataclass
class GuardianRunSummary:
    run_id: str
    mode: str
    status: str = "running"
    account_count: int = 0
    scanned_account_count: int = 0
    credit_count: int = 0
    redeemable_credit_count: int = 0
    warning_count: int = 0
    redemption_attempt_count: int = 0
    redemption_count: int = 0
    error_count: int = 0
    notification_error_count: int = 0

    def serialized(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Alert:
    key: str
    line: str


class NotificationError(RuntimeError):
    def __init__(self, error_code: str):
        super().__init__(f"notification failed ({error_code})")
        self.error_code = error_code


class CommandNotifier:
    """Invoke a reviewed command without a shell; the message is appended as --message."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 30.0,
        require_private_receipt: bool = True,
    ):
        if not command:
            raise ValueError("notification command must not be empty")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self.require_private_receipt = require_private_receipt

    def notify(self, message: str) -> None:
        child_environment = {
            "HOME": os.environ.get("HOME", "/root"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PATH": os.defpath,
        }
        try:
            result = subprocess.run(
                [*self.command, "--message", message],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=child_environment,
            )
        except subprocess.TimeoutExpired:
            raise NotificationError("timeout") from None
        except OSError as exc:
            raise NotificationError(f"exec_{type(exc).__name__}") from None
        if result.returncode != 0:
            raise NotificationError(f"exit_{result.returncode}")
        if self.require_private_receipt:
            try:
                receipt = json.loads(result.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError):
                raise NotificationError("invalid_private_receipt") from None
            if not isinstance(receipt, dict) or any(
                (
                    receipt.get("status") != "sent",
                    receipt.get("policy") != "personal-first",
                    receipt.get("route_kind") != "private",
                    receipt.get("requester_key") != "seth-ori",
                    receipt.get("destination_ref") != "seth-ori",
                )
            ):
                raise NotificationError("invalid_private_receipt")


class Guardian:
    def __init__(
        self,
        *,
        source: GuardianSource,
        audit: AuditStore,
        notifier: CommandNotifier | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.source = source
        self.audit = audit
        self.notifier = notifier
        self.clock = clock

    def run(self, *, mode: str, dry_run: bool) -> GuardianRunSummary:
        started_at = self.clock()
        run_id = self.audit.start_run(mode=mode, now=started_at)
        summary = GuardianRunSummary(run_id=run_id, mode=mode)
        alerts: list[Alert] = []
        try:
            descriptors = self.source.list_accounts()
        except Exception as exc:
            error_code = _safe_error_code(exc)
            summary.error_count += 1
            summary.status = "failed"
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="account_inventory_failed",
                severity="error",
                details={"error_code": error_code},
            )
            self.audit.finish_run(
                run_id=run_id,
                now=self.clock(),
                status=summary.status,
                summary=summary.serialized(),
            )
            return summary

        summary.account_count = len(descriptors)
        if not descriptors:
            summary.error_count += 1
            summary.status = "failed"
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="account_inventory_empty",
                severity="error",
                details={},
            )

        for descriptor in descriptors:
            self._scan_account(
                run_id=run_id,
                mode=mode,
                descriptor=descriptor,
                dry_run=dry_run,
                summary=summary,
                alerts=alerts,
            )

        if summary.account_count > 0 and summary.scanned_account_count == 0:
            summary.status = "failed"
        elif summary.error_count:
            summary.status = "degraded"
        elif summary.status == "running":
            summary.status = "ok"

        if self.notifier is not None and alerts:
            self._send_alerts(run_id=run_id, summary=summary, alerts=alerts)
            if summary.error_count and summary.status == "ok":
                summary.status = "degraded"

        self.audit.finish_run(
            run_id=run_id,
            now=self.clock(),
            status=summary.status,
            summary=summary.serialized(),
        )
        return summary

    def manual_redeem(
        self,
        *,
        account_label: str,
        expires_at: datetime,
        reason: str,
        dry_run: bool,
    ) -> GuardianRunSummary:
        run_id = self.audit.start_run(mode="manual_dry_run" if dry_run else "manual", now=self.clock())
        summary = GuardianRunSummary(run_id=run_id, mode="manual_dry_run" if dry_run else "manual")
        alerts: list[Alert] = []
        try:
            matches = [item for item in self.source.list_accounts() if item.label == account_label]
            summary.account_count = len(matches)
            if len(matches) != 1:
                raise PayloadError("manual redemption requires one exact account-label match")
            initial = self.source.refresh_account(matches[0])
            summary.scanned_account_count = 1
            summary.credit_count = len(initial.credits)
            self.audit.record_snapshot(run_id=run_id, phase="manual_inventory", observation=initial)
            matching = [
                credit
                for credit in initial.credits
                if credit.expires_at == expires_at and credit.is_redeemable
            ]
            if len(matching) != 1:
                raise PayloadError("manual redemption requires one exact redeemable expiry match")
            self._recheck_and_redeem(
                run_id=run_id,
                descriptor=matches[0],
                expected=matching[0],
                reason=reason,
                dry_run=dry_run,
                summary=summary,
                alerts=alerts,
                enforce_horizon=False,
            )
        except Exception as exc:
            summary.error_count += 1
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="manual_redemption_failed",
                severity="error",
                account_label=account_label,
                expires_at=expires_at,
                details={"error_code": _safe_error_code(exc), "reason": reason[:240]},
            )
        summary.status = "degraded" if summary.error_count else "ok"
        if self.notifier is not None and alerts:
            self._send_alerts(run_id=run_id, summary=summary, alerts=alerts)
        self.audit.finish_run(
            run_id=run_id,
            now=self.clock(),
            status=summary.status,
            summary=summary.serialized(),
        )
        return summary

    def _scan_account(
        self,
        *,
        run_id: str,
        mode: str,
        descriptor: AccountDescriptor,
        dry_run: bool,
        summary: GuardianRunSummary,
        alerts: list[Alert],
    ) -> None:
        try:
            observation = self.source.refresh_account(descriptor)
        except Exception as exc:
            error_code = _safe_error_code(exc)
            summary.error_count += 1
            broker_state = exc.broker_state if isinstance(exc, AccountScanError) else {}
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="account_scan_failed",
                severity="error",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                details={"error_code": error_code, "broker_state": broker_state},
            )
            day = self.clock().date().isoformat()
            alerts.append(
                Alert(
                    key=f"account-error:{descriptor.account_ref}:{error_code}:{day}",
                    line=f"ERROR {html.escape(descriptor.label)} could not be checked ({error_code}).",
                )
            )
            return

        summary.scanned_account_count += 1
        summary.credit_count += len(observation.credits)
        self.audit.record_snapshot(run_id=run_id, phase="inventory", observation=observation)
        self._reconcile_pending_attempts(run_id=run_id, observation=observation, alerts=alerts, summary=summary)

        candidates: list[ResetCredit] = []
        for credit in observation.credits:
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="credit_observed",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=credit.credit_ref,
                expires_at=credit.expires_at,
                details=credit.sanitized(),
            )
            if not credit.is_redeemable:
                self.audit.record_event(
                    run_id=run_id,
                    now=self.clock(),
                    event_type="credit_not_redeemable",
                    severity="warning",
                    account_ref=descriptor.account_ref,
                    account_label=descriptor.label,
                    credit_ref=credit.credit_ref,
                    expires_at=credit.expires_at,
                    details={
                        "status": credit.status,
                        "reset_type": credit.reset_type,
                        "supported_by_plan": credit.supported_by_plan,
                    },
                )
                continue
            summary.redeemable_credit_count += 1
            assert credit.expires_at is not None
            remaining = credit.expires_at - self.clock()
            if remaining <= timedelta(0):
                summary.error_count += 1
                self.audit.record_event(
                    run_id=run_id,
                    now=self.clock(),
                    event_type="credit_expired_unprotected",
                    severity="error",
                    account_ref=descriptor.account_ref,
                    account_label=descriptor.label,
                    credit_ref=credit.credit_ref,
                    expires_at=credit.expires_at,
                    details={"observed_seconds_after_expiry": int(-remaining.total_seconds())},
                )
                alerts.append(
                    Alert(
                        key=(
                            f"expired:{descriptor.account_ref}:{credit.credit_ref}:"
                            f"{utc_iso(credit.expires_at)}"
                        ),
                        line=(
                            f"ERROR {html.escape(descriptor.label)} credit was still listed after expiry "
                            f"{html.escape(utc_iso(credit.expires_at))}."
                        ),
                    )
                )
                continue
            warning_emitted = self._record_warnings(
                run_id=run_id,
                mode=mode,
                observation=observation,
                credit=credit,
                remaining=remaining,
                summary=summary,
                alerts=alerts,
            )
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="credit_decision",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=credit.credit_ref,
                expires_at=credit.expires_at,
                details={
                    "decision": "recheck_for_redemption"
                    if remaining <= AUTO_REDEEM_HORIZON
                    else "wait",
                    "remaining_seconds": int(remaining.total_seconds()),
                    "new_warning_emitted": warning_emitted,
                },
            )
            if remaining <= AUTO_REDEEM_HORIZON:
                candidates.append(credit)

        for candidate in candidates:
            self._recheck_and_redeem(
                run_id=run_id,
                descriptor=descriptor,
                expected=candidate,
                reason="automatic_within_two_hours",
                dry_run=dry_run,
                summary=summary,
                alerts=alerts,
                enforce_horizon=True,
            )

    def _record_warnings(
        self,
        *,
        run_id: str,
        mode: str,
        observation: AccountObservation,
        credit: ResetCredit,
        remaining: timedelta,
        summary: GuardianRunSummary,
        alerts: list[Alert],
    ) -> bool:
        emitted = False
        assert credit.expires_at is not None
        for threshold_hours in WARNING_THRESHOLDS_HOURS:
            if remaining > timedelta(hours=threshold_hours):
                continue
            alert = Alert(
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
            claimed = self.audit.claim_warning(
                run_id=run_id,
                mode=mode,
                now=self.clock(),
                account_ref=observation.descriptor.account_ref,
                credit=credit,
                threshold_hours=threshold_hours,
            )
            if claimed:
                emitted = True
                summary.warning_count += 1
                late_by = max(
                    0,
                    int(
                        timedelta(hours=threshold_hours).total_seconds()
                        - remaining.total_seconds()
                    ),
                )
                self.audit.record_event(
                    run_id=run_id,
                    now=self.clock(),
                    event_type="expiry_warning",
                    severity="warning",
                    account_ref=observation.descriptor.account_ref,
                    account_label=observation.descriptor.label,
                    credit_ref=credit.credit_ref,
                    expires_at=credit.expires_at,
                    threshold_hours=threshold_hours,
                    details={
                        "remaining_seconds": int(remaining.total_seconds()),
                        "late_by_seconds": late_by,
                        "usage_state": observation.usage_state,
                    },
                )
            if mode == "live":
                # Reconstruct every due live alert on each run. The notification
                # outbox suppresses receipts already marked sent and retries any
                # pending/failed threshold after a crash or transient send error.
                alerts.append(alert)
        return emitted

    def _recheck_and_redeem(
        self,
        *,
        run_id: str,
        descriptor: AccountDescriptor,
        expected: ResetCredit,
        reason: str,
        dry_run: bool,
        summary: GuardianRunSummary,
        alerts: list[Alert],
        enforce_horizon: bool,
    ) -> None:
        assert expected.expires_at is not None
        try:
            fresh = self.source.refresh_account(descriptor)
            self.audit.record_snapshot(run_id=run_id, phase="pre_redemption_recheck", observation=fresh)
        except Exception as exc:
            summary.error_count += 1
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_recheck_failed",
                severity="error",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=expected.credit_ref,
                expires_at=expected.expires_at,
                details={"error_code": _safe_error_code(exc), "reason": reason},
            )
            alerts.append(
                Alert(
                    key=(
                        f"recheck-error:{descriptor.account_ref}:{expected.credit_ref}:"
                        f"{utc_iso(expected.expires_at)}:{_safe_error_code(exc)}"
                    ),
                    line=f"ERROR {html.escape(descriptor.label)} fresh redemption recheck failed.",
                )
            )
            return

        exact = fresh.find_credit(expected.credit_ref)
        if exact is None or not exact.is_redeemable:
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_skipped_after_fresh_recheck",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=expected.credit_ref,
                expires_at=expected.expires_at,
                details={
                    "reason": "exact_credit_absent_or_not_redeemable",
                    "fresh_available_count": fresh.available_count,
                },
            )
            return
        assert exact.expires_at is not None
        if exact.expires_at != expected.expires_at:
            summary.error_count += 1
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_skipped_expiry_mismatch",
                severity="error",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=expected.credit_ref,
                expires_at=expected.expires_at,
                details={
                    "reason": "exact_credit_expiry_changed_on_fresh_recheck",
                    "expected_expires_at": utc_iso(expected.expires_at),
                    "fresh_expires_at": utc_iso(exact.expires_at),
                },
            )
            alerts.append(
                Alert(
                    key=(
                        f"expiry-mismatch:{descriptor.account_ref}:{expected.credit_ref}:"
                        f"{utc_iso(expected.expires_at)}:{utc_iso(exact.expires_at)}"
                    ),
                    line=(
                        f"ERROR {html.escape(descriptor.label)} exact credit expiry changed during "
                        "the fresh redemption recheck; no consume was attempted."
                    ),
                )
            )
            return
        remaining = exact.expires_at - self.clock()
        if remaining <= timedelta(0):
            summary.error_count += 1
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_skipped_expired",
                severity="error",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=exact.credit_ref,
                expires_at=exact.expires_at,
                details={"remaining_seconds": int(remaining.total_seconds())},
            )
            return
        if enforce_horizon and remaining > AUTO_REDEEM_HORIZON:
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_skipped_outside_horizon",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=exact.credit_ref,
                expires_at=exact.expires_at,
                details={"remaining_seconds": int(remaining.total_seconds())},
            )
            return
        if dry_run:
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_suppressed_dry_run",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=exact.credit_ref,
                expires_at=exact.expires_at,
                details={"reason": reason, "fresh_recheck_completed": True},
            )
            return
        self._execute_attempt(
            run_id=run_id,
            observation=fresh,
            credit=exact,
            reason=reason,
            summary=summary,
            alerts=alerts,
        )

    def _execute_attempt(
        self,
        *,
        run_id: str,
        observation: AccountObservation,
        credit: ResetCredit,
        reason: str,
        summary: GuardianRunSummary,
        alerts: list[Alert],
    ) -> None:
        attempt = self.audit.start_or_resume_attempt(
            run_id=run_id,
            now=self.clock(),
            observation=observation,
            credit=credit,
            reason=reason,
        )
        summary.redemption_attempt_count += 1
        self.audit.record_event(
            run_id=run_id,
            now=self.clock(),
            event_type="redemption_attempt_started",
            account_ref=observation.descriptor.account_ref,
            account_label=observation.descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            attempt_id=attempt.attempt_id,
            details={"reason": reason, "resumed": attempt.resumed},
        )
        try:
            result = self.source.consume_credit(observation, credit, attempt.idempotency_key)
        except Exception as exc:
            error_code = _safe_error_code(exc)
            uncertain = isinstance(exc, RemoteCallError) and exc.ambiguous
            self.audit.update_attempt(
                attempt_id=attempt.attempt_id,
                now=self.clock(),
                status="uncertain" if uncertain else "failed",
                error_code=error_code,
                details={"transport_ambiguous": uncertain},
            )
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_attempt_failed",
                severity="error",
                account_ref=observation.descriptor.account_ref,
                account_label=observation.descriptor.label,
                credit_ref=credit.credit_ref,
                expires_at=credit.expires_at,
                attempt_id=attempt.attempt_id,
                details={"error_code": error_code, "transport_ambiguous": uncertain},
            )
            summary.error_count += 1
            alerts.append(
                Alert(
                    key=f"attempt-error:{attempt.attempt_id}:{error_code}",
                    line=(
                        f"ERROR {html.escape(observation.descriptor.label)} redemption attempt "
                        f"failed ({error_code}); audit attempt {attempt.attempt_id[:12]}."
                    ),
                )
            )
            return

        try:
            post = self.source.refresh_account(observation.descriptor)
            self.audit.record_snapshot(run_id=run_id, phase="post_redemption_verification", observation=post)
        except Exception as exc:
            error_code = _safe_error_code(exc)
            self.audit.update_attempt(
                attempt_id=attempt.attempt_id,
                now=self.clock(),
                status="verification_failed",
                outcome=result.code,
                windows_reset=result.windows_reset,
                verification="post_state_unavailable",
                error_code=error_code,
            )
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_verification_failed",
                severity="error",
                account_ref=observation.descriptor.account_ref,
                account_label=observation.descriptor.label,
                credit_ref=credit.credit_ref,
                expires_at=credit.expires_at,
                attempt_id=attempt.attempt_id,
                details={"outcome": result.code, "error_code": error_code},
            )
            summary.error_count += 1
            alerts.append(
                Alert(
                    key=f"verification-error:{attempt.attempt_id}",
                    line=(
                        f"ERROR {html.escape(observation.descriptor.label)} returned {result.code}, "
                        f"but the post-state check failed; attempt {attempt.attempt_id[:12]}."
                    ),
                )
            )
            return

        post_credit = post.find_credit(credit.credit_ref)
        still_available = post_credit is not None and post_credit.is_redeemable
        self._complete_attempt_from_result(
            run_id=run_id,
            attempt=attempt,
            observation=observation,
            credit=credit,
            result=result,
            still_available=still_available,
            post=post,
            summary=summary,
            alerts=alerts,
        )

    def _complete_attempt_from_result(
        self,
        *,
        run_id: str,
        attempt: RedemptionAttempt,
        observation: AccountObservation,
        credit: ResetCredit,
        result: ConsumeResult,
        still_available: bool,
        post: AccountObservation,
        summary: GuardianRunSummary,
        alerts: list[Alert],
    ) -> None:
        success = False
        verification = "exact_credit_still_available" if still_available else "exact_credit_absent"
        status = "completed"
        severity = "info"
        if result.code in {"reset", "already_redeemed"}:
            success = not still_available
            status = "succeeded" if success else "verification_failed"
        elif result.code == "no_credit":
            success = not still_available
            status = "reconciled_absent" if success else "failed"
        elif result.code == "nothing_to_reset":
            success = not still_available
            status = "reconciled_absent" if success else "completed"
        if status in {"failed", "verification_failed"}:
            severity = "error"
            summary.error_count += 1
        if success:
            summary.redemption_count += 1
        self.audit.update_attempt(
            attempt_id=attempt.attempt_id,
            now=self.clock(),
            status=status,
            outcome=result.code,
            windows_reset=result.windows_reset,
            verification=verification,
            error_code=None if severity == "info" else "credit_remained_available",
            details={
                "pre_available_count": observation.available_count,
                "post_available_count": post.available_count,
            },
        )
        self.audit.record_event(
            run_id=run_id,
            now=self.clock(),
            event_type="redemption_attempt_completed",
            severity=severity,
            account_ref=observation.descriptor.account_ref,
            account_label=observation.descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            attempt_id=attempt.attempt_id,
            details={
                "outcome": result.code,
                "windows_reset": result.windows_reset,
                "verification": verification,
                "status": status,
                "pre_available_count": observation.available_count,
                "post_available_count": post.available_count,
            },
        )
        if success:
            alerts.append(
                Alert(
                    key=f"redemption-success:{attempt.attempt_id}",
                    line=(
                        f"SUCCESS {html.escape(observation.descriptor.label)} credit handled: "
                        f"{result.code}, {result.windows_reset} window(s) reset, exact credit absent "
                        f"after verification; attempt {attempt.attempt_id[:12]}."
                    ),
                )
            )
        elif severity == "error":
            alerts.append(
                Alert(
                    key=f"redemption-invalid:{attempt.attempt_id}",
                    line=(
                        f"ERROR {html.escape(observation.descriptor.label)} returned {result.code}, "
                        f"but the exact credit remained available; attempt {attempt.attempt_id[:12]}."
                    ),
                )
            )

    def _reconcile_pending_attempts(
        self,
        *,
        run_id: str,
        observation: AccountObservation,
        alerts: list[Alert],
        summary: GuardianRunSummary,
    ) -> None:
        available_refs = {credit.credit_ref for credit in observation.credits if credit.is_redeemable}
        for pending in self.audit.pending_attempts_for_account(
            account_ref=observation.descriptor.account_ref
        ):
            if pending["credit_ref"] in available_refs:
                continue
            expiry = parse_timestamp(pending["expires_at"], field_name="attempt.expires_at")
            if self.clock() >= expiry:
                status = "expired_unverified"
                verification = "credit_absent_only_after_expiry"
                severity = "error"
                summary.error_count += 1
            else:
                status = "reconciled_absent"
                verification = "credit_absent_on_later_fresh_scan"
                severity = "info"
                summary.redemption_count += 1
            self.audit.update_attempt(
                attempt_id=pending["attempt_id"],
                now=self.clock(),
                status=status,
                outcome=pending.get("outcome"),
                windows_reset=pending.get("windows_reset"),
                verification=verification,
            )
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="redemption_attempt_reconciled",
                severity=severity,
                account_ref=observation.descriptor.account_ref,
                account_label=observation.descriptor.label,
                credit_ref=pending["credit_ref"],
                expires_at=expiry,
                attempt_id=pending["attempt_id"],
                details={"status": status, "verification": verification},
            )
            alerts.append(
                Alert(
                    key=f"attempt-reconciled:{pending['attempt_id']}:{status}",
                    line=(
                        f"{'SUCCESS' if severity == 'info' else 'ERROR'} "
                        f"{html.escape(observation.descriptor.label)} pending reset attempt "
                        f"{pending['attempt_id'][:12]} reconciled as {status}."
                    ),
                )
            )

    def _send_alerts(
        self,
        *,
        run_id: str,
        summary: GuardianRunSummary,
        alerts: list[Alert],
    ) -> None:
        assert self.notifier is not None
        due = [
            alert
            for alert in alerts
            if self.audit.notification_due(
                notification_key=alert.key,
                run_id=run_id,
                now=self.clock(),
            )
        ]
        if not due:
            return
        for batch in _alert_batches(due):
            message = "\n".join(["<b>Codex reset guardian</b>", *[alert.line for alert in batch]])
            try:
                self.notifier.notify(message)
            except NotificationError as exc:
                self.audit.record_notification_result(
                    notification_keys=[alert.key for alert in batch],
                    now=self.clock(),
                    sent=False,
                    error_code=exc.error_code,
                )
                self.audit.record_event(
                    run_id=run_id,
                    now=self.clock(),
                    event_type="notification_failed",
                    severity="error",
                    details={"error_code": exc.error_code, "alert_count": len(batch)},
                )
                summary.error_count += 1
                summary.notification_error_count += 1
                continue
            self.audit.record_notification_result(
                notification_keys=[alert.key for alert in batch],
                now=self.clock(),
                sent=True,
                error_code=None,
            )
            self.audit.record_event(
                run_id=run_id,
                now=self.clock(),
                event_type="notification_sent",
                details={"alert_count": len(batch), "route": "requester_private"},
            )


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, RemoteCallError):
        return f"{exc.endpoint}:{exc.error_code}"
    if isinstance(exc, AccountScanError):
        return exc.error_code
    if isinstance(exc, PayloadError):
        return f"payload:{type(exc).__name__}"
    if isinstance(exc, NotificationError):
        return f"notification:{exc.error_code}"
    return f"unexpected:{type(exc).__name__}"


def _alert_batches(alerts: list[Alert], *, maximum_length: int = 3800) -> list[list[Alert]]:
    header_length = len("<b>Codex reset guardian</b>\n")
    batches: list[list[Alert]] = []
    current: list[Alert] = []
    current_length = header_length
    for alert in alerts:
        line_length = len(alert.line) + 1
        if current and current_length + line_length > maximum_length:
            batches.append(current)
            current = []
            current_length = header_length
        if line_length + header_length > maximum_length:
            alert = Alert(key=alert.key, line=alert.line[: maximum_length - header_length - 2] + "…")
            line_length = len(alert.line) + 1
        current.append(alert)
        current_length += line_length
    if current:
        batches.append(current)
    return batches
