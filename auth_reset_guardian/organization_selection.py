# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exact selection comparison for the last pre-consume guard."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .models import utc_iso
from .organization_fingerprint import organization_decision_key

if TYPE_CHECKING:
    from .organization_policy import OrganizationDecision
    from .organization_runtime import OrganizationInventory


@dataclass(frozen=True)
class SelectionMismatch:
    """One reason the original exact selection may no longer be consumed."""

    reason: str
    loud: bool
    expected_expires_at: str | None
    fresh_expires_at: str | None


def compare_selection(
    initial: OrganizationDecision,
    fresh: OrganizationDecision,
    inventory: OrganizationInventory,
) -> SelectionMismatch | None:
    """Compare account, credit, expiry, weekly reset, and organization evidence.

    Returns:
        A mismatch when any required identity or evidence changed; otherwise None.

    Raises:
        ValueError: The original decision does not contain a selection.
    """
    selected = initial.selection
    if selected is None:
        message = "an organization selection is required for comparison"
        raise ValueError(message)
    expected_expiry = selected.credit.expires_at
    expected_text = utc_iso(expected_expiry) if expected_expiry is not None else None
    account_ref = selected.observation.descriptor.account_ref
    fresh_observation = inventory.observations.get(account_ref)
    fresh_credit = (
        fresh_observation.find_credit(selected.credit.credit_ref)
        if fresh_observation
        else None
    )
    fresh_expiry = fresh_credit.expires_at if fresh_credit is not None else None
    fresh_text = utc_iso(fresh_expiry) if fresh_expiry is not None else None
    if fresh_credit is not None and fresh_expiry != expected_expiry:
        return SelectionMismatch(
            reason="exact_credit_expiry_changed",
            loud=True,
            expected_expires_at=expected_text,
            fresh_expires_at=fresh_text,
        )
    fresh_evidence = next(
        (item for item in fresh.evidence if item.account_ref == account_ref),
        None,
    )
    if (
        fresh_evidence is not None
        and fresh_evidence.state != "indeterminate"
        and (fresh_evidence.weekly_reset_at is None
             or abs((fresh_evidence.weekly_reset_at - selected.weekly_reset_at).total_seconds()) > 2)
    ):
        return SelectionMismatch(
            reason="weekly_reset_changed",
            loud=True,
            expected_expires_at=expected_text,
            fresh_expires_at=fresh_text,
        )
    if fresh.state != "redeem":
        return SelectionMismatch(
            reason=f"fresh_organization_state_{fresh.state}",
            loud=False,
            expected_expires_at=expected_text,
            fresh_expires_at=fresh_text,
        )
    # Provider countdown-derived reset timestamps can jitter by one second.
    # Normalize only bounded timestamp drift; fresh policy, exact credit identity,
    # expiry, capacity states and subscription boundaries still must agree.
    initial_by_ref = {item.account_ref: item for item in initial.evidence}
    normalized = []
    for item in fresh.evidence:
        previous = initial_by_ref.get(item.account_ref)
        if previous is not None:
            if (item.weekly_reset_at is not None and previous.weekly_reset_at is not None
                and abs((item.weekly_reset_at - previous.weekly_reset_at).total_seconds()) <= 2):
                item = replace(item, weekly_reset_at=previous.weekly_reset_at)
            if (len(item.exhausted_window_resets) == len(previous.exhausted_window_resets)
                and all(abs(a - b) <= 2 for a, b in zip(
                    item.exhausted_window_resets, previous.exhausted_window_resets, strict=True))):
                item = replace(item, exhausted_window_resets=previous.exhausted_window_resets)
        normalized.append(item)
    fresh_selection = fresh.selection
    if (fresh_selection is not None
        and abs((fresh_selection.weekly_reset_at - selected.weekly_reset_at).total_seconds()) <= 2):
        fresh_selection = replace(fresh_selection, weekly_reset_at=selected.weekly_reset_at)
    normalized_key = organization_decision_key(evidence=normalized, selection=fresh_selection)
    if normalized_key != initial.decision_key:
        return SelectionMismatch(
            reason="organization_evidence_or_selection_changed",
            loud=False,
            expected_expires_at=expected_text,
            fresh_expires_at=fresh_text,
        )
    return None
