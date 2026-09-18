# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exact selection comparison for the last pre-consume guard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import utc_iso

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
        and fresh_evidence.weekly_reset_at != selected.weekly_reset_at
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
    if fresh.decision_key != initial.decision_key:
        return SelectionMismatch(
            reason="organization_evidence_or_selection_changed",
            loud=False,
            expected_expires_at=expected_text,
            fresh_expires_at=fresh_text,
        )
    return None
