# Copyright (c) 2026 PitchAI. All rights reserved.
"""Complete inventory evidence for expiry-based reset decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .organization_capacity import MAX_FUTURE_SKEW, MAX_OBSERVATION_AGE, account_capacity_evidence

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from .models import AccountDescriptor, AccountObservation
    from .organization_capacity import AccountCapacityEvidence


def capacity_evidence(
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


def inventory_is_fresh(evidence: Sequence[AccountCapacityEvidence], *, now: datetime) -> bool:
    """Require a successful fresh observation for every enabled account.

    Returns:
        Whether the complete inventory can safely determine expiry priority.
    """
    for item in evidence:
        if item.state == "disabled":
            continue
        if item.captured_at is None or item.reason == "authoritative refresh failed or is missing":
            return False
        age = now - item.captured_at
        if age > MAX_OBSERVATION_AGE or age < -MAX_FUTURE_SKEW:
            return False
    return True
