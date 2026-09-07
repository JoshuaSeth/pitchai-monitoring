# Copyright (c) 2026 PitchAI. All rights reserved.
"""Production guardian using organization exhaustion instead of expiry redemption."""

from __future__ import annotations

import html
from contextlib import closing
from datetime import timedelta
from typing import TYPE_CHECKING, final

from .guardian import Alert, Guardian, GuardianRunSummary
from .models import utc_iso
from .organization_audit import OrganizationAttemptStore
from .organization_reconciliation import reconcile_pending_attempts
from .organization_refresh import refresh_organization
from .organization_runtime import OrganizationRunContext
from .organization_workflow import OrganizationWorkflow

if TYPE_CHECKING:
    from .models import AccountObservation, ResetCredit
    from .organization_runtime import OrganizationInventory


class OrganizationGuardian(Guardian):
    """Schedule at most one reset only after fresh organization exhaustion proof."""

    @final
    def run(self, *, mode: str, dry_run: bool) -> GuardianRunSummary:
        """Run one complete scheduled organization decision.

        Returns:
            The durable summary for this scheduled fire.
        """
        run_id = self.audit.start_run(mode=mode, now=self.clock())
        summary = GuardianRunSummary(run_id=run_id, mode=mode)
        alerts: list[Alert] = []
        with closing(OrganizationAttemptStore(self.audit.path)) as claims:
            context = OrganizationRunContext(
                source=self.source,
                audit=self.audit,
                claims=claims,
                clock=self.clock,
                run_id=run_id,
                summary=summary,
                alerts=alerts,
            )
            claims.reconcile_terminal_attempts()
            inventory = refresh_organization(context, phase="initial_inventory")
            summary.account_count = len(inventory.descriptors)
            if not inventory.descriptors and not inventory.inventory_failed:
                self._record_empty_inventory(context)
            redemption_suppressed = self._record_inventory(
                context,
                inventory,
                mode=mode,
            )
            claims.reconcile_terminal_attempts()
            OrganizationWorkflow(context).apply(
                inventory,
                dry_run=dry_run,
                redemption_suppressed=redemption_suppressed,
            )
        self._finish_summary(summary)
        if alerts and self.notifier is not None:
            self._send_alerts(run_id=run_id, summary=summary, alerts=alerts)
            if summary.error_count and summary.status == "ok":
                summary.status = "degraded"
        completed_at = self.clock()
        serialized_summary = summary.serialized()
        self.audit.finish_run(
            summary=serialized_summary,
            status=summary.status,
            now=completed_at,
            run_id=run_id,
        )
        return summary

    @staticmethod
    def _record_empty_inventory(context: OrganizationRunContext) -> None:
        context.summary.error_count += 1
        context.summary.status = "failed"
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="account_inventory_empty",
            severity="error",
            details={},
        )

    def _record_inventory(
        self,
        context: OrganizationRunContext,
        inventory: OrganizationInventory,
        *,
        mode: str,
    ) -> bool:
        """Record inventory details and detect a recovery action fence.

        Returns:
            True when exact-identity recovery must suppress this pass.
        """
        redemption_suppressed = False
        for descriptor in inventory.descriptors:
            if not descriptor.enabled:
                context.audit.record_event(
                    run_id=context.run_id,
                    now=context.clock(),
                    event_type="account_excluded_disabled",
                    account_ref=descriptor.account_ref,
                    account_label=descriptor.label,
                    details={
                        "reason": "disabled_accounts_are_not_usable_capacity_evidence",
                    },
                )
                continue
            observation = inventory.observations.get(descriptor.account_ref)
            if observation is None:
                continue
            context.summary.scanned_account_count += 1
            context.summary.credit_count += len(observation.credits)
            redemption_suppressed = (
                reconcile_pending_attempts(context, observation)
                or redemption_suppressed
            )
            for credit in observation.credits:
                self._record_credit(context, observation, credit, mode=mode)
        return redemption_suppressed

    def _record_credit(
        self,
        context: OrganizationRunContext,
        observation: AccountObservation,
        credit: ResetCredit,
        *,
        mode: str,
    ) -> None:
        descriptor = observation.descriptor
        context.audit.record_event(
            event_type="credit_observed",
            account_ref=descriptor.account_ref,
            account_label=descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            run_id=context.run_id,
            now=context.clock(),
            details=credit.sanitized(),
        )
        if not credit.is_redeemable:
            ineligible_details = {
                "status": credit.status,
                "reset_type": credit.reset_type,
                "supported_by_plan": credit.supported_by_plan,
            }
            context.audit.record_event(
                event_type="credit_not_redeemable",
                severity="warning",
                account_ref=descriptor.account_ref,
                account_label=descriptor.label,
                credit_ref=credit.credit_ref,
                expires_at=credit.expires_at,
                run_id=context.run_id,
                now=context.clock(),
                details=ineligible_details,
            )
            return
        context.summary.redeemable_credit_count += 1
        expires_at = credit.expires_at
        if expires_at is None:
            message = "redeemable credit is missing its expiry"
            raise RuntimeError(message)
        remaining = expires_at - context.clock()
        if remaining <= timedelta(0):
            self._record_expired_credit(context, observation, credit, remaining)
            return
        warning_emitted = self._record_warnings(
            run_id=context.run_id,
            mode=mode,
            observation=observation,
            credit=credit,
            remaining=remaining,
            summary=context.summary,
            alerts=context.alerts,
        )
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="credit_decision",
            account_ref=descriptor.account_ref,
            account_label=descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            details={
                "decision": "organization_exhaustion_evaluation",
                "remaining_seconds": int(remaining.total_seconds()),
                "new_warning_emitted": warning_emitted,
                "expiry_horizon_is_not_an_automatic_redemption_gate": True,
            },
        )

    @staticmethod
    def _record_expired_credit(
        context: OrganizationRunContext,
        observation: AccountObservation,
        credit: ResetCredit,
        remaining: timedelta,
    ) -> None:
        descriptor = observation.descriptor
        observed_seconds = int(-remaining.total_seconds())
        now = context.clock()
        context.summary.error_count += 1
        context.audit.record_event(
            run_id=context.run_id,
            now=now,
            event_type="credit_expired_unprotected",
            severity="error",
            account_ref=descriptor.account_ref,
            account_label=descriptor.label,
            credit_ref=credit.credit_ref,
            expires_at=credit.expires_at,
            details={"observed_seconds_after_expiry": observed_seconds},
        )
        expiry_text = utc_iso(credit.expires_at) if credit.expires_at else "unknown"
        key = f"expired:{descriptor.account_ref}:{credit.credit_ref}:{expiry_text}"
        line = (
            f"ERROR {html.escape(descriptor.label)} credit was still listed after "
            f"expiry {html.escape(expiry_text)}."
        )
        context.alerts.append(Alert(key=key, line=line))

    @staticmethod
    def _finish_summary(summary: GuardianRunSummary) -> None:
        if summary.account_count > 0 and summary.scanned_account_count == 0:
            summary.status = "failed"
        elif summary.error_count:
            summary.status = "degraded"
        elif summary.status == "running":
            summary.status = "ok"
