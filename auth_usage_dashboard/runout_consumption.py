# Copyright (c) 2026 PitchAI. All rights reserved.
"""Consume capacity in earliest-expiry order."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .value_parsing import UTC

if TYPE_CHECKING:
    from .models import CapacityScheduleEvent


def consume(
    capacities: dict[str, float],
    expiries: dict[str, datetime],
    demand: float,
) -> None:
    """Consume demand from the capacity that expires soonest."""
    ordered = sorted(
        capacities,
        key=lambda label: (
            expiries.get(label, datetime.max.replace(tzinfo=UTC)),
            label,
        ),
    )
    for label in ordered:
        if demand <= 0:
            return
        consumed = min(capacities[label], demand)
        capacities[label] -= consumed
        demand -= consumed


def next_expiries(
    capacities: dict[str, float],
    events: list[CapacityScheduleEvent],
    *,
    horizon_end: datetime,
) -> dict[str, datetime]:
    """Map current account capacity to its next scheduled expiry.

    Returns:
        The resulting collection.

    """
    expiries: dict[str, datetime] = {}
    for label in capacities:
        expiries[label] = following_expiry(
            label,
            events,
            after=None,
            horizon_end=horizon_end,
        )
    return expiries


def following_expiry(
    label: str,
    events: list[CapacityScheduleEvent],
    *,
    after: datetime | None,
    horizon_end: datetime,
) -> datetime:
    """Return an account's next reset or a value beyond the horizon."""
    for event in events:
        if event["account_label"] == label and (after is None or event["at"] > after):
            return event["at"]
    return horizon_end + timedelta(seconds=1)
