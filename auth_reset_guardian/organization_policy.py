# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure organization-wide capacity and reset-credit selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from .organization_capacity import account_capacity_evidence
from .organization_fingerprint import organization_decision_key

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from .models import AccountDescriptor, AccountObservation, ResetCredit
    from .organization_capacity import AccountCapacityEvidence


DecisionState = Literal[
    "indeterminate",
    "not_exhausted",
    "no_eligible_credit",
    "redeem",
]
MINIMUM_WEEKLY_RESET_DISTANCE = timedelta(hours=48)


@dataclass(frozen=True)
class RedemptionSelection:
    """One exact account and credit selected by the pure policy."""

    observation: AccountObservation
    credit: ResetCredit
    weekly_reset_at: datetime


@dataclass(frozen=True)
class OrganizationDecision:
    """Organization-wide decision with a stable concurrency fingerprint."""

    state: DecisionState
    reason: str
    evidence: tuple[AccountCapacityEvidence, ...]
    decision_key: str
    selection: RedemptionSelection | None = None


@dataclass(frozen=True)
class DecisionOutcome:
    """State, reason, and optional selection before fingerprinting."""

    state: DecisionState
    reason: str
    selection: RedemptionSelection | None


def evaluate_organization(
    *,
    descriptors: Sequence[AccountDescriptor],
    observations: Mapping[str, AccountObservation],
    failed_account_refs: set[str],
    now: datetime,
) -> OrganizationDecision:
    """Require fresh proof that every enabled account has zero remaining capacity.

    Returns:
        One deterministic organization decision and, when eligible, one selection.
    """
    evidence = _capacity_evidence(
        descriptors=descriptors,
        observations=observations,
        failed_account_refs=failed_account_refs,
        now=now,
    )
    selections = _eligible_selections(
        evidence=evidence,
        observations=observations,
        now=now,
    )
    outcome = _decision_outcome(evidence=evidence, selections=selections)
    decision_key = organization_decision_key(
        evidence=evidence,
        selection=outcome.selection,
    )
    return OrganizationDecision(
        outcome.state,
        outcome.reason,
        evidence,
        decision_key,
        outcome.selection,
    )


def _capacity_evidence(
    *,
    descriptors: Sequence[AccountDescriptor],
    observations: Mapping[str, AccountObservation],
    failed_account_refs: set[str],
    now: datetime,
) -> tuple[AccountCapacityEvidence, ...]:
    """Build deterministic per-account evidence from one inventory.

    Returns:
        One capacity conclusion for every broker account.
    """
    return tuple(
        account_capacity_evidence(
            descriptor=descriptor,
            observation=observations.get(descriptor.account_ref),
            refresh_failed=descriptor.account_ref in failed_account_refs,
            now=now,
        )
        for descriptor in sorted(descriptors, key=lambda item: item.account_ref)
    )


def _decision_outcome(
    *,
    evidence: Sequence[AccountCapacityEvidence],
    selections: Sequence[RedemptionSelection],
) -> DecisionOutcome:
    """Classify complete evidence and choose at most one reset.

    Returns:
        The organization state and its optional exact selection.
    """
    usable = tuple(item for item in evidence if item.state != "disabled")
    if not usable or any(item.state == "indeterminate" for item in evidence):
        return DecisionOutcome(
            "indeterminate",
            "usable account inventory is empty or has failed, missing, contradictory, or stale evidence",
            None,
        )
    if any(item.state == "available" for item in usable):
        return DecisionOutcome(
            "not_exhausted",
            "at least one usable account has authoritative remaining capacity",
            None,
        )
    if not selections:
        return DecisionOutcome(
            "no_eligible_credit",
            "all usable accounts are exhausted, but no banked reset has a weekly reset more than 48 hours away",
            None,
        )
    selection = max(
        selections,
        key=lambda item: (
            item.weekly_reset_at,
            item.observation.descriptor.account_ref,
            _expiry_sort_value(item.credit),
        ),
    )
    return DecisionOutcome(
        "redeem",
        "all usable accounts are exhausted and one strictly eligible reset was selected",
        selection,
    )


def _eligible_selections(
    *,
    evidence: Sequence[AccountCapacityEvidence],
    observations: Mapping[str, AccountObservation],
    now: datetime,
) -> tuple[RedemptionSelection, ...]:
    candidates: list[RedemptionSelection] = []
    exhausted = (item for item in evidence if item.state == "exhausted")
    with_weekly_reset = (item for item in exhausted if item.weekly_reset_at is not None)
    for item in with_weekly_reset:
        weekly_reset_at = item.weekly_reset_at
        if (
            weekly_reset_at is None
            or weekly_reset_at - now <= MINIMUM_WEEKLY_RESET_DISTANCE
        ):
            continue
        observation = observations.get(item.account_ref)
        if observation is None or observation.available_count <= 0:
            continue
        redeemable = (credit for credit in observation.credits if credit.is_redeemable)
        with_expiry = (credit for credit in redeemable if credit.expires_at is not None)
        unexpired = [
            credit for credit in with_expiry if _expiry_sort_value(credit) > now
        ]
        if not unexpired:
            continue
        candidates.append(
            RedemptionSelection(
                observation,
                min(unexpired, key=_expiry_sort_value),
                weekly_reset_at,
            ),
        )
    return tuple(candidates)


def _expiry_sort_value(credit: ResetCredit) -> datetime:
    expires_at = credit.expires_at
    if expires_at is None:
        message = "selected reset credit is missing its expiry"
        raise ValueError(message)
    return expires_at
