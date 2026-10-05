# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict timestamp operations for redacted scheduling-capacity timelines."""

from __future__ import annotations

from datetime import UTC, datetime


def aware_datetime(value: str | None) -> datetime | None:
    """Parse one internal ISO timestamp while rejecting absent or naive values.

    Returns:
        The normalized UTC timestamp, or None when absent or timezone-naive.
    """
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)
