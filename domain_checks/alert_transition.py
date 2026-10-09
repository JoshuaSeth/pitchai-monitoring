# Copyright (c) 2026 PitchAI. All rights reserved.
"""Debounce observed health without merging independent domain histories."""

from __future__ import annotations

from typing import TypedDict, Unpack


class HealthObservation(TypedDict):
    """Complete inputs to the existing keyword-only transition contract."""

    prev_effective_ok: bool
    observed_ok: bool
    fail_streak: int
    success_streak: int
    down_after_failures: int
    up_after_successes: int


def update_effective_ok(**observation: Unpack[HealthObservation]) -> tuple[bool, int, int, bool]:
    """Advance consecutive observations using the configured down/up limits.

    Returns:
        Effective health, failure streak, success streak and a DOWN edge.
        Repeated failures retain DOWN without creating a second edge; recovery
        requires the configured number of consecutive successful observations.
    """
    down_after_failures = max(1, int(observation["down_after_failures"]))
    up_after_successes = max(1, int(observation["up_after_successes"]))
    if observation["observed_ok"]:
        success_streak = int(observation["success_streak"]) + 1
        fail_streak = 0
    else:
        fail_streak = int(observation["fail_streak"]) + 1
        success_streak = 0
    if observation["prev_effective_ok"]:
        next_effective_ok = fail_streak < down_after_failures
    else:
        next_effective_ok = success_streak >= up_after_successes
    alerted_down = observation["prev_effective_ok"] and not next_effective_ok
    return next_effective_ok, fail_streak, success_streak, alerted_down
