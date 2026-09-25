# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scalar, timestamp, range, and sampling helpers for monitor summaries."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from domain_checks.history import Sample
    from e2e_registry.monitor_types import MonitorRecord, MonitorRecords, MonitorValue

_DEFAULT_RANGE_SECONDS = 86_400.0
_RANGE_SECONDS = {
    "6h": 21_600.0,
    "6hr": 21_600.0,
    "6hrs": 21_600.0,
    "12h": 43_200.0,
    "12hr": 43_200.0,
    "12hrs": 43_200.0,
    "24h": _DEFAULT_RANGE_SECONDS,
    "1d": _DEFAULT_RANGE_SECONDS,
    "day": _DEFAULT_RANGE_SECONDS,
    "48h": 172_800.0,
    "2d": 172_800.0,
    "7d": 604_800.0,
    "week": 604_800.0,
    "14d": 1_209_600.0,
    "2w": 1_209_600.0,
    "two_weeks": 1_209_600.0,
    "30d": 2_592_000.0,
    "month": 2_592_000.0,
}


def safe_float(value: MonitorValue) -> float | None:
    """Return a numeric value or ``None`` for unsupported state data."""
    if not isinstance(value, bool | int | float | str):
        return None
    try:
        return float(value)
    except (ValueError, OverflowError):
        return None


def safe_int(value: MonitorValue) -> int | None:
    """Return an integer value or ``None`` for unsupported state data."""
    if not isinstance(value, bool | int | float | str):
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):
        return None


def safe_timestamp(value: MonitorValue) -> float | None:
    """Return a positive Unix timestamp decoded from monitor state."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        timestamp = float(value)
        return timestamp if timestamp > 0 else None
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        timestamp = float(raw)
    except ValueError:
        iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            return None
        aware = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        timestamp = aware.timestamp()
    return timestamp if timestamp > 0 else None


def downsample[Item](items: list[Item], *, max_points: int) -> list[Item]:
    """Return a bounded sample while preserving the final point."""
    bounded_maximum = max(1, int(max_points))
    if len(items) <= bounded_maximum:
        return items
    step = math.ceil(len(items) / float(bounded_maximum))
    sampled = items[::step]
    if sampled and sampled[-1] is not items[-1]:
        sampled.append(items[-1])
    return sampled


def history_range_utc(history_by_domain: dict[str, list[Sample]]) -> tuple[float | None, float | None]:
    """Return the minimum and maximum timestamps in normalized history."""
    history_values = history_by_domain.values()
    populated_histories = filter(None, history_values)
    endpoints = [(items[0][0], items[-1][0]) for items in populated_histories]
    if not endpoints:
        return None, None
    return min(start for start, _end in endpoints), max(end for _start, end in endpoints)


def resolve_range(*, now_ts: float, range_label: str) -> tuple[float, float]:
    """Return inclusive bounds for a supported dashboard range label."""
    duration = _RANGE_SECONDS.get(str(range_label or "").strip().lower(), _DEFAULT_RANGE_SECONDS)
    until_ts = float(now_ts)
    return until_ts - duration, until_ts


def monitor_mapping(value: MonitorValue) -> MonitorRecord:
    """Return a monitor mapping or an empty mapping at the state-data edge."""
    return cast("MonitorRecord", value) if isinstance(value, dict) else {}


def monitor_records(value: MonitorValue) -> MonitorRecords:
    """Return only mapping records from an untrusted monitor list."""
    if not isinstance(value, list):
        return []
    mappings = (item for item in value if isinstance(item, dict))
    return [cast("MonitorRecord", item) for item in mappings]
