# Copyright (c) 2026 PitchAI. All rights reserved.
"""Coordinated organization-wide decision, recheck, and single redemption."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from .guardian import Alert
from .models import utc_iso
from .organization_active_claim import resolve_active_mismatch
from .organization_claim import ClaimRequest
from .organization_policy import evaluate_organization
from .organization_redemption import OrganizationRedemption
from .organization_refresh import refresh_organization
from .organization_reporting import record_organization_decision, sanitized_decision
from .organization_selection import compare_selection
from .organization_verification import verify_restored_capacity

if TYPE_CHECKING:
    from .organization_claim import CoordinatedAttempt
    from .organization_policy import OrganizationDecision, RedemptionSelection
    from .organization_runtime import OrganizationInventory, OrganizationRunContext
    from .organization_selection import SelectionMismatch


class OrganizationWorkflow:
    """Apply the exhaustion-only policy to one complete initial inventory."""

    _context: OrganizationRunContext

    def __init__(self, context: OrganizationRunContext) -> None:
        """Bind one scheduled run's audit, source, and claim state."""
        self._context = context

    def apply(
        self,
        inventory: OrganizationInventory,
        *,
        dry_run: bool,
        redemption_suppressed: bool,
    ) -> None:
        """Evaluate, claim, recheck, and at most once consume one exact credit.

        Raises:
            RuntimeError: A redeem decision violates its selection invariant.
        """
        context = self._context
        initial = evaluate_organization(
            descriptors=inventory.descriptors,
            observations=inventory.observations,
            failed_account_refs=inventory.failed_account_refs,
            now=context.clock(),
        )
        self.record_decision(initial, phase="initial_inventory")
        if initial.state != "redeem" or redemption_suppressed:
            return
        selection = initial.selection
        if selection is None:
            message = "redeem decision is missing its exact selection"
            raise RuntimeError(message)
        attempt = None
        if not dry_run:
            attempt = context.claims.claim(
                ClaimRequest(
                    run_id=context.run_id,
                    now=context.clock(),
                    decision_key=initial.decision_key,
                    selection=selection,
                ),
            )
            self._record_claim(initial, attempt)
            if not attempt.executable:
                if attempt.status == "active_selection_mismatch":
                    resolve_active_mismatch(context, attempt, selection)
                return
        fresh_inventory = refresh_organization(
            context,
            phase="pre_redemption_recheck",
            selection=selection,
        )
        fresh = evaluate_organization(
            descriptors=fresh_inventory.descriptors,
            observations=fresh_inventory.observations,
            failed_account_refs=fresh_inventory.failed_account_refs,
            now=context.clock(),
        )
        self.record_decision(fresh, phase="pre_redemption_recheck")
        mismatch = compare_selection(initial, fresh, fresh_inventory)
        if mismatch is not None:
            self._cancel_new_claim(attempt, mismatch)
            self._record_mismatch(selection, fresh, mismatch)
            return
        fresh_selection = fresh.selection
        if fresh_selection is None:
            message = "fresh redeem decision is missing its exact selection"
            raise RuntimeError(message)
        if dry_run:
            self._record_dry_run(fresh, fresh_selection)
            return
        if attempt is None:
            message = "live organization redemption is missing its durable attempt"
            raise RuntimeError(message)
        capacity_check = OrganizationRedemption(context).execute(
            attempt,
            fresh_selection,
        )
        if capacity_check:
            verify_restored_capacity(context)

    def record_decision(self, decision: OrganizationDecision, *, phase: str) -> None:
        """Persist one workflow decision through the shared audit serializer."""
        context = self._context
        record_organization_decision(context, decision, phase=phase)

    def _record_claim(
        self,
        decision: OrganizationDecision,
        attempt: CoordinatedAttempt,
    ) -> None:
        context = self._context
        selection = decision.selection
        if selection is None:
            message = "organization claim is missing its selected credit"
            raise RuntimeError(message)
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="organization_redemption_claim",
            account_ref=selection.observation.descriptor.account_ref,
            account_label=selection.observation.descriptor.label,
            credit_ref=selection.credit.credit_ref,
            expires_at=selection.credit.expires_at,
            attempt_id=attempt.attempt_id,
            details={
                "decision_key": decision.decision_key,
                "status": attempt.status,
                "resumed": attempt.resumed,
                "executable": attempt.executable,
            },
        )

    def _cancel_new_claim(
        self,
        attempt: CoordinatedAttempt | None,
        mismatch: SelectionMismatch,
    ) -> None:
        if attempt is None or attempt.resumed:
            return
        context = self._context
        context.audit.update_attempt(
            attempt_id=attempt.attempt_id,
            now=context.clock(),
            status="cancelled_before_consume",
            verification="fresh_organization_recheck_rejected",
            error_code=mismatch.reason,
            details={"consume_attempted": False},
        )
        context.claims.mark(
            attempt_id=attempt.attempt_id,
            state="cancelled_before_consume",
            now=context.clock(),
        )

    def _record_mismatch(
        self,
        selection: RedemptionSelection,
        fresh: OrganizationDecision,
        mismatch: SelectionMismatch,
    ) -> None:
        context = self._context
        if mismatch.loud:
            context.summary.error_count += 1
            key = (
                f"organization-selection-mismatch:{selection.observation.descriptor.account_ref}:"
                f"{selection.credit.credit_ref}:{mismatch.reason}"
            )
            line = (
                f"ERROR {html.escape(selection.observation.descriptor.label)} reset "
                f"{mismatch.reason}; "
                "the organization-wide consume was suppressed."
            )
            context.alerts.append(Alert(key=key, line=line))
        details = {
            "reason": mismatch.reason,
            "expected_expires_at": mismatch.expected_expires_at,
            "fresh_expires_at": mismatch.fresh_expires_at,
            "initial_weekly_reset_at": utc_iso(selection.weekly_reset_at),
            "fresh_decision": sanitized_decision(fresh, now=context.clock()),
            "consume_attempted": False,
        }
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="organization_redemption_suppressed_after_recheck",
            severity="error" if mismatch.loud else "info",
            account_ref=selection.observation.descriptor.account_ref,
            account_label=selection.observation.descriptor.label,
            credit_ref=selection.credit.credit_ref,
            expires_at=selection.credit.expires_at,
            details=details,
        )

    def _record_dry_run(
        self,
        decision: OrganizationDecision,
        selection: RedemptionSelection,
    ) -> None:
        context = self._context
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="organization_redemption_suppressed_dry_run",
            account_ref=selection.observation.descriptor.account_ref,
            account_label=selection.observation.descriptor.label,
            credit_ref=selection.credit.credit_ref,
            expires_at=selection.credit.expires_at,
            details={
                "decision_key": decision.decision_key,
                "weekly_reset_at": utc_iso(selection.weekly_reset_at),
                "fresh_organization_recheck_completed": True,
            },
        )
