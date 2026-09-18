# Copyright (c) 2026 PitchAI. All rights reserved.
"""Secret-safe serialization for organization redemption policy evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from .models import utc_iso

if TYPE_CHECKING:
    from datetime import datetime

    from .organization_capacity import AccountCapacityEvidence
    from .organization_policy import OrganizationDecision
    from .organization_runtime import OrganizationRunContext


class SanitizedSelection(TypedDict):
    """Secret-safe selected reset identity and weekly distance."""

    account_ref: str
    account_label: str
    credit_ref: str
    expires_at: str | None
    weekly_reset_at: str
    weekly_reset_distance_seconds: int


class SanitizedAccount(TypedDict):
    """Secret-safe capacity evidence for one broker account."""

    account_ref: str
    account_label: str
    state: str
    reason: str
    captured_at: str | None
    exhausted_window_resets: list[int]
    weekly_reset_at: str | None
    weekly_reset_distance_seconds: int | None


class SanitizedDecision(TypedDict):
    """Complete secret-safe organization decision audit payload."""

    state: str
    reason: str
    decision_key: str
    usable_account_count: int
    disabled_account_count: int
    exhausted_account_count: int
    accounts: list[SanitizedAccount]
    selection: SanitizedSelection | None
    phase: str | None


def sanitized_decision(
    decision: OrganizationDecision,
    *,
    now: datetime,
) -> SanitizedDecision:
    """Return decision evidence suitable for the guardian audit log.

    Returns:
        A secret-safe JSON object containing the decision and account evidence.
    """
    selection: SanitizedSelection | None = None
    if decision.selection is not None:
        credit = decision.selection.credit
        selection = {
            "account_ref": decision.selection.observation.descriptor.account_ref,
            "account_label": decision.selection.observation.descriptor.label,
            "credit_ref": credit.credit_ref,
            "expires_at": utc_iso(credit.expires_at) if credit.expires_at else None,
            "weekly_reset_at": utc_iso(decision.selection.weekly_reset_at),
            "weekly_reset_distance_seconds": int(
                (decision.selection.weekly_reset_at - now).total_seconds(),
            ),
        }
    accounts: list[SanitizedAccount] = []
    for item in decision.evidence:
        account = _sanitized_account(item, now=now)
        accounts.append(account)
    return {
        "state": decision.state,
        "reason": decision.reason,
        "decision_key": decision.decision_key,
        "usable_account_count": sum(
            item.state != "disabled" for item in decision.evidence
        ),
        "disabled_account_count": sum(
            item.state == "disabled" for item in decision.evidence
        ),
        "exhausted_account_count": sum(
            item.state == "exhausted" for item in decision.evidence
        ),
        "accounts": accounts,
        "selection": selection,
        "phase": None,
    }


def record_organization_decision(
    context: OrganizationRunContext,
    decision: OrganizationDecision,
    *,
    phase: str,
) -> None:
    """Persist one complete, secret-safe organization decision."""
    severity = "error" if decision.state == "indeterminate" else "info"
    if severity == "error":
        context.summary.error_count += 1
    details = sanitized_decision(decision, now=context.clock())
    details["phase"] = phase
    context.audit.record_event(
        run_id=context.run_id,
        now=context.clock(),
        event_type="organization_redemption_decision",
        severity=severity,
        details=dict(details),
    )


def _sanitized_account(
    evidence: AccountCapacityEvidence,
    *,
    now: datetime,
) -> SanitizedAccount:
    weekly_seconds = None
    if evidence.weekly_reset_at is not None:
        weekly_seconds = int((evidence.weekly_reset_at - now).total_seconds())
    return {
        "account_ref": evidence.account_ref,
        "account_label": evidence.account_label,
        "state": evidence.state,
        "reason": evidence.reason,
        "captured_at": utc_iso(evidence.captured_at) if evidence.captured_at else None,
        "exhausted_window_resets": list(evidence.exhausted_window_resets),
        "weekly_reset_at": utc_iso(evidence.weekly_reset_at)
        if evidence.weekly_reset_at
        else None,
        "weekly_reset_distance_seconds": weekly_seconds,
    }
