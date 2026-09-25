# Copyright (c) 2026 PitchAI. All rights reserved.
"""Classify normalized broker account availability."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .value_parsing import parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityWindow


class AccountStatus(NamedTuple):
    """Represent normalized status and safety-floor state."""

    value: str
    reason: str
    safety_floor: bool


class StatusInputs(NamedTuple):
    """Bundle facts used to classify broker availability."""

    enabled: bool
    usage_available: bool
    availability: str
    five_hour: CapacityWindow
    weekly: CapacityWindow
    now: datetime
    minimum_remaining: float


def classify_account_status(inputs: StatusInputs) -> AccountStatus:
    """Map broker state to the dashboard availability vocabulary.

    Returns:
        The resulting value.

    """
    five_remaining = inputs.five_hour["remaining_percent"]
    weekly_remaining = inputs.weekly["remaining_percent"]
    five_reset = parse_datetime(inputs.five_hour["reset_at"])
    weekly_reset = parse_datetime(inputs.weekly["reset_at"])
    five_reset_due = five_reset is not None and five_reset <= inputs.now
    weekly_reset_due = weekly_reset is not None and weekly_reset <= inputs.now
    safety_floor = bool(
        inputs.availability == "available"
        and five_remaining is not None
        and five_remaining <= inputs.minimum_remaining,
    )
    inventory_status = _inventory_status(inputs, safety_floor=safety_floor)
    if inventory_status is not None:
        return inventory_status
    capacity_status = _capacity_status(
        weekly_remaining=weekly_remaining,
        five_remaining=five_remaining,
        weekly_reset_due=weekly_reset_due,
        five_reset_due=five_reset_due,
        safety_floor=safety_floor,
    )
    if capacity_status is not None:
        return capacity_status
    return _available_status(inputs, reset_due=five_reset_due or weekly_reset_due)


def _inventory_status(
    inputs: StatusInputs,
    *,
    safety_floor: bool,
) -> AccountStatus | None:
    if not inputs.enabled:
        return AccountStatus("disabled", "Disabled in broker inventory", safety_floor)
    if inputs.availability == "auth_invalid":
        return AccountStatus(
            "auth_invalid",
            "Login or token refresh required",
            safety_floor,
        )
    if not inputs.usage_available or inputs.availability == "unknown":
        return AccountStatus("unknown", "Usage state unavailable", safety_floor)
    return None


def _capacity_status(
    *,
    weekly_remaining: float | None,
    five_remaining: float | None,
    weekly_reset_due: bool,
    five_reset_due: bool,
    safety_floor: bool,
) -> AccountStatus | None:
    if weekly_remaining is not None and weekly_remaining <= 0 and not weekly_reset_due:
        return AccountStatus(
            "weekly_limited",
            "Weekly usage window exhausted",
            safety_floor,
        )
    if five_remaining is not None and five_remaining <= 0 and not five_reset_due:
        return AccountStatus(
            "five_hour_limited",
            "Five-hour usage window exhausted",
            safety_floor,
        )
    if safety_floor:
        return AccountStatus(
            "five_hour_limited",
            "Held at broker five-hour safety floor",
            safety_floor=True,
        )
    return None


def _available_status(inputs: StatusInputs, *, reset_due: bool) -> AccountStatus:
    if inputs.availability == "rate_limited":
        if reset_due:
            return AccountStatus(
                "unknown",
                "Reset is due; awaiting a fresh provider state",
                safety_floor=False,
            )
        if inputs.five_hour["reported"]:
            return AccountStatus(
                "five_hour_limited",
                "Five-hour usage window limited",
                safety_floor=False,
            )
        return AccountStatus(
            "unknown",
            "Provider reported a limit without a five-hour window",
            safety_floor=False,
        )
    if inputs.availability == "available":
        return AccountStatus("available", "Selectable now", safety_floor=False)
    return AccountStatus("unknown", "Unrecognized broker availability", safety_floor=False)


def account_auth_valid(availability: str, *, usage_available: bool) -> bool | None:
    """Normalize the account authentication state.

    Returns:
        The resulting value.

    """
    if availability == "auth_invalid":
        return False
    if availability in {"available", "rate_limited"} or usage_available:
        return True
    return None
