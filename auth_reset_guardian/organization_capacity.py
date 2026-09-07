# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fresh per-account capacity evidence for organization reset decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from .models import AccountDescriptor, AccountObservation


CapacityState = Literal["disabled", "indeterminate", "available", "exhausted"]
MAX_OBSERVATION_AGE = timedelta(minutes=2)
MAX_FUTURE_SKEW = timedelta(seconds=30)
WEEKLY_WINDOW_MIN_SECONDS = 6 * 24 * 60 * 60
WEEKLY_WINDOW_MAX_SECONDS = 8 * 24 * 60 * 60
FULLY_USED_PERCENT = 100


@dataclass(frozen=True)
class AccountCapacityEvidence:
    """Sanitized capacity conclusion for one broker account."""

    account_ref: str
    account_label: str
    state: CapacityState
    reason: str
    captured_at: datetime | None
    exhausted_window_resets: tuple[int, ...] = ()
    weekly_reset_at: datetime | None = None


def account_capacity_evidence(
    *,
    descriptor: AccountDescriptor,
    observation: AccountObservation | None,
    refresh_failed: bool,
    now: datetime,
) -> AccountCapacityEvidence:
    """Classify one broker account from a fresh provider observation.

    Returns:
        A fail-closed capacity classification with secret-safe evidence.
    """
    if not descriptor.enabled:
        return AccountCapacityEvidence(
            descriptor.account_ref,
            descriptor.label,
            "disabled",
            "disabled by broker",
            None,
        )
    if refresh_failed or observation is None:
        captured_at = observation.captured_at if observation else None
        return AccountCapacityEvidence(
            descriptor.account_ref,
            descriptor.label,
            "indeterminate",
            "authoritative refresh failed or is missing",
            captured_at,
        )
    age = now - observation.captured_at
    if age > MAX_OBSERVATION_AGE or age < -MAX_FUTURE_SKEW:
        return AccountCapacityEvidence(
            descriptor.account_ref,
            descriptor.label,
            "indeterminate",
            "authoritative observation is stale or future-dated",
            observation.captured_at,
        )
    windows = _reported_windows(observation)
    weekly_reset = _weekly_reset_at(observation=observation, windows=windows)
    state, reason, exhausted_resets = _capacity_state(
        observation=observation,
        windows=windows,
    )
    return AccountCapacityEvidence(
        descriptor.account_ref,
        descriptor.label,
        state,
        reason,
        observation.captured_at,
        exhausted_resets,
        weekly_reset,
    )


def _capacity_state(
    *,
    observation: AccountObservation,
    windows: Sequence[dict[str, int]],
) -> tuple[CapacityState, str, tuple[int, ...]]:
    if not windows:
        return "indeterminate", "provider reported no measurable capacity window", ()
    exhausted_reset_values: list[int] = []
    for window in windows:
        if window["used_percent"] < FULLY_USED_PERCENT:
            continue
        reset_value = window.get("reset_at", 0)
        exhausted_reset_values.append(reset_value)
    exhausted_resets = tuple(sorted(exhausted_reset_values))
    allowed = observation.usage_state.get("allowed")
    limit_reached = observation.usage_state.get("limit_reached")
    if exhausted_resets and (allowed or not limit_reached):
        return (
            "indeterminate",
            "provider scheduling flags conflict with a zero-remaining window",
            exhausted_resets,
        )
    if exhausted_resets:
        return (
            "exhausted",
            "at least one authoritative capacity window has zero percent remaining",
            exhausted_resets,
        )
    if limit_reached or not allowed:
        return (
            "indeterminate",
            "provider scheduling flags conflict with positive measured capacity",
            (),
        )
    return (
        "available",
        "all authoritative capacity windows have positive remaining capacity",
        (),
    )


def _reported_windows(observation: AccountObservation) -> tuple[dict[str, int], ...]:
    windows: list[dict[str, int]] = []
    for key in ("primary_window", "secondary_window"):
        untyped_window = observation.usage_state.get(key)
        if not isinstance(untyped_window, dict):
            continue
        raw_window = cast("dict[str, int | bool | None]", untyped_window)
        used_percent = raw_window.get("used_percent")
        if isinstance(used_percent, bool) or not isinstance(used_percent, int):
            continue
        window: dict[str, int] = {"used_percent": used_percent}
        for field in ("limit_window_seconds", "reset_after_seconds", "reset_at"):
            value = raw_window.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                window[field] = value
        windows.append(window)
    return tuple(windows)


def _weekly_reset_at(
    *,
    observation: AccountObservation,
    windows: Sequence[dict[str, int]],
) -> datetime | None:
    candidates: set[datetime] = set()
    for window in windows:
        duration = window.get("limit_window_seconds")
        if (
            duration is None
            or not WEEKLY_WINDOW_MIN_SECONDS <= duration <= WEEKLY_WINDOW_MAX_SECONDS
        ):
            continue
        reset_at = window.get("reset_at")
        if reset_at is not None:
            candidates.add(
                observation.captured_at.fromtimestamp(
                    reset_at,
                    tz=observation.captured_at.tzinfo,
                ),
            )
            continue
        reset_after = window.get("reset_after_seconds")
        if reset_after is not None:
            candidates.add(observation.captured_at + timedelta(seconds=reset_after))
    return candidates.pop() if len(candidates) == 1 else None
