# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure organization-wide capacity and reset-credit selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .expiry_drain_order import expiry_drain_accounts, should_preserve_reset
from .expiry_inventory import capacity_evidence, inventory_is_fresh
from .organization_fingerprint import organization_decision_key
from .subscription_expiry import (
    confirmed_end_date,
    confirmed_end_time,
    subscription_may_have_ended,
)

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
    """Drain confirmed expiring accounts first; preserve fleet fallback for unknown dates.

    Returns:
        One deterministic organization decision and, when eligible, one selection.
    """
    evidence = capacity_evidence(
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
    outcome = _decision_outcome(
        evidence=evidence, selections=selections, observations=observations, now=now,
    )
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


def _decision_outcome(
    *,
    evidence: Sequence[AccountCapacityEvidence],
    selections: Sequence[RedemptionSelection],
    observations: Mapping[str, AccountObservation],
    now: datetime,
) -> DecisionOutcome:
    """Classify complete evidence and choose at most one reset.

    Returns:
        The organization state and its optional exact selection.
    """
    if not inventory_is_fresh(evidence, now=now):
        return DecisionOutcome(
            "indeterminate",
            "complete fresh inventory is required before redemption",
            None,
        )
    by_ref = {item.account_ref: item for item in evidence}
    for observation in expiry_drain_accounts(observations, now=now):
        item = by_ref[observation.descriptor.account_ref]
        if item.state == "indeterminate":
            return DecisionOutcome(
                "indeterminate",
                "expiry-priority account lacks fresh effective-capacity evidence",
                None,
            )
        if item.state == "available":
            return DecisionOutcome(
                "not_exhausted",
                "continue draining the earliest-expiring usable account",
                None,
            )
        selection = next(
            (
                entry
                for entry in selections
                if entry.observation.descriptor.account_ref == item.account_ref
            ),
            None,
        )
        if selection is not None:
            return DecisionOutcome(
                "redeem",
                "restore the earliest-expiring exhausted account before moving to later expiry",
                selection,
            )
        # No eligible bank remains, or the four-day / two-day waiting exception applies.
    return _fleet_outcome(evidence=evidence, selections=selections)


def _fleet_outcome(
    *,
    evidence: Sequence[AccountCapacityEvidence],
    selections: Sequence[RedemptionSelection],
) -> DecisionOutcome:
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
            "all accounts exhausted, but no reset meets credit, subscription, and weekly-distance eligibility",
            None,
        )
    selection = min(
        selections,
        key=lambda item: (
            confirmed_end_date(item.observation) or "9999-12-31",
            _subscription_time_rank(item.observation),
            _expiry_sort_value(item.credit),
            item.observation.descriptor.account_ref,
            item.credit.credit_ref,
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
        if weekly_reset_at is None or weekly_reset_at <= now:
            continue
        observation = observations.get(item.account_ref)
        if observation is None or observation.available_count <= 0:
            continue
        if subscription_may_have_ended(observation, now=now):
            continue
        redeemable = (credit for credit in observation.credits if credit.is_redeemable)
        with_expiry = (credit for credit in redeemable if credit.expires_at is not None)
        unexpired = [
            credit for credit in with_expiry if _expiry_sort_value(credit) > now
        ]
        if not unexpired:
            continue
        earliest = min(
            unexpired,
            key=lambda credit: (_expiry_sort_value(credit), credit.credit_ref),
        )
        if should_preserve_reset(
            observation, earliest, weekly_reset_at=weekly_reset_at, now=now,
        ):
            continue
        candidates.append(
            RedemptionSelection(
                observation,
                earliest,
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


def _subscription_time_rank(observation: AccountObservation) -> float:
    exact = confirmed_end_time(observation)
    return exact.timestamp() if exact else float("inf")
