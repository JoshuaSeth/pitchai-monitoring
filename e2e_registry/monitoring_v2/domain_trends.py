# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded domain history access and 24-hour trend projection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.monitoring_contracts.json_types import (
    bool_value,
    float_value,
    optional_object,
    value_list,
)

if TYPE_CHECKING:
    from domain_checks.monitoring_contracts.json_types import JsonObject, JsonValue

_MIN_OBSERVATION_FIELDS = 2
_HTTP_LATENCY_FIELDS = 3
_BROWSER_LATENCY_FIELDS = 4
_HISTORY_WINDOW_SECONDS = 86_400.0


def domain_trend(history: list[JsonValue], *, now_ts: float) -> JsonObject:
    """Build a bounded 24-hour trend from existing monitor samples.

    Returns:
        Trend direction, availability, and down-sampled chart points.
    """
    recent: list[list[JsonValue]] = []
    for raw in history:
        sample = value_list(raw)
        timestamp = float_value(sample[0]) if sample else None
        if (
            len(sample) >= _MIN_OBSERVATION_FIELDS
            and timestamp is not None
            and timestamp >= now_ts - _HISTORY_WINDOW_SECONDS
        ):
            recent.append(sample)
    step = max(1, (len(recent) + 17) // 18)
    plotted = recent[::step]
    if recent and plotted[-1] is not recent[-1]:
        plotted.append(recent[-1])
    successful = sum(1 for sample in recent if bool_value(sample[1]) is True)
    points: list[JsonValue] = [
        {
            "observed_at_ts": float_value(sample[0]),
            "ok": bool_value(sample[1]),
            "http_elapsed_ms": float_value(sample[2]) if len(sample) >= _HTTP_LATENCY_FIELDS else None,
            "browser_elapsed_ms": float_value(sample[3]) if len(sample) >= _BROWSER_LATENCY_FIELDS else None,
        }
        for sample in plotted
    ]
    return {
        "direction": "degrading" if recent and bool_value(recent[-1][1]) is False else "stable",
        "observations": len(recent),
        "availability_pct": (100.0 * successful / len(recent)) if recent else None,
        "points": points,
    }


def history_for_domain(state: JsonObject, domain: str) -> list[JsonValue]:
    """Read one domain's retained sample list from normalized state.

    Returns:
        The retained sample list, or an empty list when absent.
    """
    history = optional_object(state.get("history"))
    return value_list(history.get(domain))
