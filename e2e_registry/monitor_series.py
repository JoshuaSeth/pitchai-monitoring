# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded domain and signal time-series payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from e2e_registry.monitor_values import downsample, monitor_mapping, safe_float, safe_int

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorData, MonitorRecord, MonitorSample, MonitorValue


_TS_INDEX = 0
_OK_INDEX = 1
_HTTP_INDEX = 2
_BROWSER_INDEX = 3
_STATUS_INDEX = 4


def _bounded_samples(
    items: MonitorValue,
    *,
    since_ts: float,
    until_ts: float,
    max_points: int,
) -> list[list[MonitorValue] | MonitorSample]:
    if not isinstance(items, list):
        return []
    selected: list[list[MonitorValue] | MonitorSample] = []
    for item in items:
        if not isinstance(item, list | tuple) or not item:
            continue
        timestamp = safe_float(item[_TS_INDEX])
        if timestamp is None or timestamp < float(since_ts) or timestamp > float(until_ts):
            continue
        selected.append(item)
    return downsample(selected, max_points=max_points)


def domain_timeseries(
    *,
    data: MonitorData,
    domain: str,
    since_ts: float,
    until_ts: float,
    max_points: int,
) -> MonitorRecord:
    """Return normalized, bounded samples for one monitored domain."""
    history = monitor_mapping(data.state.get("history"))
    samples = _bounded_samples(
        history.get(domain),
        since_ts=since_ts,
        until_ts=until_ts,
        max_points=max_points,
    )
    return {
        "ok": True,
        "domain": domain,
        "since_ts": float(since_ts),
        "until_ts": float(until_ts),
        "samples": [
            {
                "ts": safe_float(sample[_TS_INDEX]) if sample else None,
                "ok": bool(sample[_OK_INDEX]) if len(sample) > _OK_INDEX else None,
                "http_ms": safe_float(sample[_HTTP_INDEX]) if len(sample) > _HTTP_INDEX else None,
                "browser_ms": safe_float(sample[_BROWSER_INDEX]) if len(sample) > _BROWSER_INDEX else None,
                "status_code": safe_int(sample[_STATUS_INDEX]) if len(sample) > _STATUS_INDEX else None,
            }
            for sample in samples
        ],
    }


def signal_timeseries(
    *,
    data: MonitorData,
    signal: str,
    since_ts: float,
    until_ts: float,
    max_points: int,
) -> MonitorRecord:
    """Return bounded raw samples for one global monitoring signal."""
    histories = monitor_mapping(data.state.get("signal_history"))
    samples = _bounded_samples(
        histories.get(signal),
        since_ts=since_ts,
        until_ts=until_ts,
        max_points=max_points,
    )
    return cast(
        "MonitorRecord",
        {
            "ok": True,
            "signal": signal,
            "since_ts": float(since_ts),
            "until_ts": float(until_ts),
            "samples": samples,
        },
    )
