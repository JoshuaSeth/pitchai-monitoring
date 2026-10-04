# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scalar conversion and sampling rules for the existing dashboard contracts."""

from __future__ import annotations

import math
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from domain_checks.cycle_values import required_float, required_int

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue
    from domain_checks.history import Sample


def safe_float(value: ConfigValue) -> float | None:
    """Convert accepted scalars, preserving None for failed conversions.

    Returns:
        The existing float result, including nonfinite values, or None.
    """
    with suppress(TypeError, ValueError, OverflowError):
        return required_float(value)
    return None


def safe_int(value: ConfigValue) -> int | None:
    """Apply integer conversion without inventing zero for invalid input.

    Returns:
        The converted value, or None after a conversion failure.
    """
    with suppress(TypeError, ValueError, OverflowError):
        return required_int(value)
    return None


def safe_timestamp(value: ConfigValue) -> float | None:
    """Interpret positive numeric or ISO times with naive values in UTC.

    Returns:
        A positive timestamp, or None for an unavailable timestamp.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        return timestamp if timestamp > 0 else None
    raw = str(value).strip()
    if not raw:
        return None
    timestamp: float | None = None
    with suppress(ValueError):
        timestamp = float(raw)
    if timestamp is None:
        iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = None
        with suppress(ValueError):
            parsed = datetime.fromisoformat(iso_value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        timestamp = parsed.timestamp()
    return timestamp if timestamp > 0 else None


def downsample[Item](items: list[Item], *, max_points: int) -> list[Item]:
    """Keep the original stride, identity comparison and mandatory last point.

    Returns:
        The original list when small enough, otherwise a sampled list of its items.
    """
    max_points = max(1, int(max_points))
    count = len(items)
    if count <= max_points:
        return items
    step = math.ceil(count / float(max_points))
    if step <= 1:
        return items
    selected = items[::step]
    if selected and selected[-1] is not items[-1]:
        selected.append(items[-1])
    return selected


def parse_range_to_seconds(rng: str) -> float:
    """Resolve the retained range aliases with the original one-day fallback.

    Returns:
        The duration in seconds without consulting a clock.
    """
    normalized = str(rng or "").strip().lower()
    ranges = (
        ({"6h", "6hr", "6hrs"}, 6 * 3600.0),
        ({"12h", "12hr", "12hrs"}, 12 * 3600.0),
        ({"48h", "2d"}, 48 * 3600.0),
        ({"7d", "week"}, 7 * 86400.0),
        ({"14d", "2w", "two_weeks"}, 14 * 86400.0),
        ({"30d", "month"}, 30 * 86400.0),
    )
    for aliases, seconds in ranges:
        if normalized in aliases:
            return seconds
    return 24 * 3600.0


def history_range_utc(history_by_domain: dict[str, list[Sample]]) -> tuple[float | None, float | None]:
    """Read only each domain's existing first and last sample boundaries.

    Returns:
        The earliest first and latest last timestamp; invalid boundaries are skipped.
    """
    minimum = None
    maximum = None
    for items in history_by_domain.values():
        if not items:
            continue
        bounds: tuple[float, float] | None = None
        with suppress(TypeError, ValueError, OverflowError, IndexError):
            bounds = required_float(items[0][0]), required_float(items[-1][0])
        if bounds is not None:
            start, end = bounds
            minimum = start if minimum is None else min(minimum, start)
            maximum = end if maximum is None else max(maximum, end)
    return minimum, maximum
