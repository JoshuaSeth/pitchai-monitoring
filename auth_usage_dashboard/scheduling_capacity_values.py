# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed scalar normalization for scheduling-capacity data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .scheduling_capacity_timeline_values import aware_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonValue


def freshness_seconds(generated_at: str | None, probe_at: str | None) -> int | None:
    """Return non-negative source age in seconds when both timestamps parse."""
    generated = _datetime(generated_at)
    probe = _datetime(probe_at)
    if generated is None or probe is None:
        return None
    return max(0, int((generated - probe).total_seconds()))


def seconds_until(value: str, *, generated_at: str | None) -> int | None:
    """Return non-negative seconds until an event when timestamps parse."""
    event_at = _datetime(value)
    generated = _datetime(generated_at)
    if event_at is None or generated is None:
        return None
    return max(0, int((event_at - generated).total_seconds()))


def measurement_status(value: JsonValue) -> str:
    """Normalize measurement status to its fail-closed member.

    Returns:
        A supported status, defaulting to unavailable.
    """
    if isinstance(value, str) and value in {"complete", "partial", "unavailable"}:
        return value
    return "unavailable"


def burn_confidence(value: JsonValue) -> str:
    """Normalize burn confidence to its fail-closed member.

    Returns:
        A supported confidence, defaulting to unavailable.
    """
    if isinstance(value, str) and value in {"high", "medium", "low", "unavailable"}:
        return value
    return "unavailable"


def runout_risk(value: JsonValue) -> str:
    """Normalize runout risk to its fail-closed member.

    Returns:
        A supported risk, defaulting to unknown.
    """
    if isinstance(value, str) and value in {"low", "medium", "high", "unknown"}:
        return value
    return "unknown"


def _datetime(value: JsonValue) -> datetime | None:
    """Parse an internal aware ISO-8601 timestamp.

    Returns:
        UTC timestamp when valid and timezone-aware, otherwise None.
    """
    return aware_datetime(value if isinstance(value, str) else None)
