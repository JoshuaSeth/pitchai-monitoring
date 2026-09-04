# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deployment validation for aggregate scheduling-capacity burn windows."""

from __future__ import annotations

from math import isclose
from typing import TYPE_CHECKING

from .scheduling_capacity_timeline_values import aware_datetime
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    require_object,
    text_value,
)

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

_BURN_WINDOW_KEYS = {
    "window_hours",
    "starts_at",
    "ends_at",
    "capacity_points",
    "capacity_points_per_hour",
    "source",
    "confidence",
    "sample_count",
    "covered_accounts",
    "coverage_percent",
    "measured_hours",
    "provider_tokens",
    "token_covered_accounts",
}
_MAX_PERCENT = 100.0
_SECONDS_PER_HOUR = 3600


def validate_burn_windows(burn_windows: JsonObject) -> None:
    """Validate bounded native-or-estimated burn evidence."""
    _require(
        condition=set(burn_windows) == {"last_hour", "last_24_hours"},
        description="burn window names",
    )
    for name, hours in (("last_hour", 1), ("last_24_hours", 24)):
        window = require_object(burn_windows.get(name), description=name)
        _require(
            condition=set(window) == _BURN_WINDOW_KEYS,
            description=f"{name} fields",
        )
        _require(
            condition=window.get("window_hours") == hours,
            description=f"{name} duration",
        )
        _require(
            condition=window.get("source")
            in {"native_broker_samples", "current_window_average"},
            description=f"{name} source",
        )
        _require(
            condition=window.get("confidence") in {"high", "medium", "low"},
            description=f"{name} confidence",
        )
        _validate_burn_window_values(window, name=name, hours=hours)


def _validate_burn_window_values(
    window: JsonObject,
    *,
    name: str,
    hours: int,
) -> None:
    """Validate one burn window's chronology, counters, and source claims."""
    starts_at = aware_datetime(text_value(window.get("starts_at")))
    ends_at = aware_datetime(text_value(window.get("ends_at")))
    duration_seconds = (
        (ends_at - starts_at).total_seconds()
        if starts_at is not None and ends_at is not None
        else None
    )
    _require(
        condition=(
            duration_seconds is not None
            and isclose(duration_seconds, hours * _SECONDS_PER_HOUR)
        ),
        description=f"{name} chronology",
    )
    counters = (
        nonnegative_integer(window.get("sample_count")),
        nonnegative_integer(window.get("covered_accounts")),
        nonnegative_integer(window.get("token_covered_accounts")),
    )
    _require(
        condition=all(counter is not None for counter in counters),
        description=f"{name} counters",
    )
    coverage = number_value(window.get("coverage_percent"))
    _require(
        condition=coverage is not None and 0.0 <= coverage <= _MAX_PERCENT,
        description=f"{name} coverage",
    )
    points = number_value(window.get("capacity_points"))
    rate = number_value(window.get("capacity_points_per_hour"))
    measured = number_value(window.get("measured_hours"))
    _require(
        condition=(
            points is not None
            and points >= 0.0
            and rate is not None
            and rate >= 0.0
            and measured is not None
            and measured >= 0.0
        ),
        description=f"{name} burn values",
    )
    provider_tokens = window.get("provider_tokens")
    _require(
        condition=provider_tokens is None
        or nonnegative_integer(provider_tokens) is not None,
        description=f"{name} provider tokens",
    )
    if window.get("source") == "current_window_average":
        _require(
            condition=coverage is not None
            and isclose(coverage, 0.0)
            and measured is not None
            and isclose(measured, 0.0)
            and provider_tokens is None,
            description=f"{name} estimated-source claims",
        )
    else:
        _require(
            condition=measured is not None and measured <= float(hours),
            description=f"{name} measured duration",
        )


def _require(*, condition: bool, description: str) -> None:
    """Raise when one burn-window invariant is false.

    Raises:
        AssertionError: If the invariant is false.
    """
    if not condition:
        message = f"invalid scheduling capacity {description}"
        raise AssertionError(message)
