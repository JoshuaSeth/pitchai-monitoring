# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained domain and signal series selection with the existing stride rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .dashboard_domain_metrics import sample_observation
from .dashboard_records import array_or_empty, object_or_empty
from .dashboard_values import downsample, parse_range_to_seconds, safe_float

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .dashboard_data import MonitorData
    from .dashboard_records import Record


def _within_window(
    items: list[ConfigValue], *, minimum_size: int, since_ts: float, until_ts: float,
) -> list[list[ConfigValue]]:
    selected: list[list[ConfigValue]] = []
    for item in items:
        if not isinstance(item, list) or len(item) < minimum_size:
            continue
        timestamp = safe_float(item[0])
        if timestamp is None or timestamp < float(since_ts) or timestamp > float(until_ts):
            continue
        selected.append(item)
    return selected


def domain_timeseries(
    *, data: MonitorData, domain: str, since_ts: float, until_ts: float, max_points: int,
) -> Record:
    """Filter inclusive time bounds before sampling and exposing domain fields.

    Returns:
        The original response shape, with invalid timestamps skipped.
    """
    histories = object_or_empty((data.state or {}).get("history"))
    # load_monitor_data normalizes this mapping to Sample lists; the cast does
    # not re-normalize or alter direct callers' retained sequences.
    items = cast("list[ConfigValue]", histories.get(domain) or [])
    selected = _within_window(items, minimum_size=2, since_ts=since_ts, until_ts=until_ts)
    sampled = downsample(selected, max_points=max_points)
    samples: list[ConfigValue] = [sample_observation(item) for item in sampled]
    return {"ok": True, "domain": domain, "since_ts": float(since_ts), "until_ts": float(until_ts), "samples": samples}


def signal_timeseries(
    *, data: MonitorData, signal: str, since_ts: float, until_ts: float, max_points: int,
) -> Record:
    """Return selected signal rows without copying their nested contents.

    Returns:
        The same inclusive window, sampling and row-identity contract.
    """
    histories = object_or_empty((data.state or {}).get("signal_history"))
    items = array_or_empty(histories.get(signal))
    selected = _within_window(items, minimum_size=1, since_ts=since_ts, until_ts=until_ts)
    samples = downsample(selected, max_points=max_points)
    return {"ok": True, "signal": signal, "since_ts": float(since_ts), "until_ts": float(until_ts),
            "samples": cast("list[ConfigValue]", samples)}


def resolve_range(*, now_ts: float, range_label: str) -> tuple[float, float]:
    """Resolve the existing relative range against the caller's clock.

    Returns:
        The original start and end timestamps.
    """
    duration = parse_range_to_seconds(range_label)
    until_ts = float(now_ts)
    return until_ts - duration, until_ts
