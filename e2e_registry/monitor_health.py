# Copyright (c) 2026 PitchAI. All rights reserved.
"""Freshness, E2E, and rolling-day monitoring health summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from e2e_registry.monitor_signals import event_kind_is_problem, event_kind_is_recovery
from e2e_registry.monitor_values import monitor_mapping, monitor_records, safe_int, safe_timestamp

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorData, MonitorRecord, MonitorRecords

_DEFAULT_INTERVAL_SECONDS = 60
_MINIMUM_STALE_SECONDS = 180
_DAY_SECONDS = 86_400.0


def summarize_freshness(
    *,
    data: MonitorData,
    now_ts: float,
    history_max_ts: float | None,
) -> MonitorRecord:
    """Return freshness status from the explicit state timestamp or history."""
    state_updated_at_ts = safe_timestamp(data.state.get("updated_at"))
    source = "state.updated_at"
    if state_updated_at_ts is None:
        state_updated_at_ts = history_max_ts
        source = "history.max_ts" if history_max_ts is not None else "unavailable"

    interval_seconds = safe_int(data.config.get("interval_seconds"))
    if interval_seconds is None or interval_seconds <= 0:
        interval_seconds = _DEFAULT_INTERVAL_SECONDS
    stale_after_seconds = max(_MINIMUM_STALE_SECONDS, interval_seconds * 3)
    if state_updated_at_ts is None:
        return {
            "status": "unknown",
            "state_updated_at_ts": None,
            "age_seconds": None,
            "interval_seconds": interval_seconds,
            "stale_after_seconds": stale_after_seconds,
            "source": source,
        }
    age_seconds = max(0.0, float(now_ts) - state_updated_at_ts)
    return {
        "status": "fresh" if age_seconds <= stale_after_seconds else "stale",
        "state_updated_at_ts": state_updated_at_ts,
        "age_seconds": age_seconds,
        "interval_seconds": interval_seconds,
        "stale_after_seconds": stale_after_seconds,
        "source": source,
    }


def _e2e_problem(test: MonitorRecord) -> MonitorRecord:
    return {
        "test_id": str(test.get("test_id") or ""),
        "test_name": str(test.get("test_name") or "Unnamed E2E test"),
        "base_url": str(test.get("base_url") or ""),
        "fail_streak": safe_int(test.get("fail_streak")) or 0,
        "last_status": str(test.get("last_status") or "unknown"),
        "last_finished_at_ts": safe_timestamp(test.get("last_finished_at_ts")),
    }


def summarize_e2e(e2e_status_summary: MonitorRecord | None, *, now_ts: float) -> MonitorRecord:
    """Return enabled E2E test health without treating missing data as healthy."""
    if not isinstance(e2e_status_summary, dict) or e2e_status_summary.get("ok") is not True:
        return {
            "status": "unavailable",
            "total_tests": None,
            "passing_tests": None,
            "failing_tests": None,
            "disabled_tests": None,
            "latest_run_at_ts": None,
            "latest_run_age_seconds": None,
            "problems": [],
        }
    tests = monitor_records(e2e_status_summary.get("tests"))
    enabled = [test for test in tests if (safe_int(test.get("enabled")) or 0) == 1]
    failing_tests = (test for test in enabled if (safe_int(test.get("effective_ok")) or 0) == 0)
    problems = [_e2e_problem(test) for test in failing_tests]
    finished_timestamps: list[float] = []
    for test in enabled:
        timestamp = safe_timestamp(test.get("last_finished_at_ts"))
        if timestamp is not None:
            finished_timestamps.append(timestamp)
    latest_run_at_ts = max(finished_timestamps, default=None)
    total_tests = len(enabled)
    failing_tests = len(problems)
    return cast(
        "MonitorRecord",
        {
            "status": "attention" if failing_tests else "healthy",
            "total_tests": total_tests,
            "passing_tests": max(0, total_tests - failing_tests),
            "failing_tests": failing_tests,
            "disabled_tests": max(0, len(tests) - total_tests),
            "latest_run_at_ts": latest_run_at_ts,
            "latest_run_age_seconds": (
                max(0.0, float(now_ts) - latest_run_at_ts) if latest_run_at_ts is not None else None
            ),
            "problems": problems,
        },
    )


def _event_timestamp(event: MonitorRecord, *, since_ts: float, now_ts: float) -> float | None:
    timestamp = safe_timestamp(event.get("ts"))
    return timestamp if timestamp is not None and since_ts <= timestamp <= now_ts else None


def summarize_daily_status(
    *,
    domains: MonitorRecords,
    events: MonitorRecords,
    open_problem_count: int,
    now_ts: float,
) -> MonitorRecord:
    """Return rolling-day availability and event totals."""
    enabled_domains = (domain for domain in domains if not bool(domain.get("disabled")))
    availability_records = [monitor_mapping(domain.get("availability_24h")) for domain in enabled_domains]
    observations = sum(safe_int(availability.get("total")) or 0 for availability in availability_records)
    successes = sum(safe_int(availability.get("ok")) or 0 for availability in availability_records)
    since_ts = float(now_ts) - _DAY_SECONDS
    daily_events = [event for event in events if _event_timestamp(event, since_ts=since_ts, now_ts=now_ts) is not None]
    timestamps: list[float] = []
    for event in daily_events:
        timestamp = safe_timestamp(event.get("ts"))
        if timestamp is not None:
            timestamps.append(timestamp)
    if observations == 0:
        status = "unknown"
    elif open_problem_count > 0:
        status = "attention"
    else:
        status = "healthy"
    return {
        "period_seconds": int(_DAY_SECONDS),
        "status": status,
        "observations": observations,
        "successful_observations": successes,
        "availability_pct": (successes / observations) * 100.0 if observations else None,
        "problem_events": sum(event_kind_is_problem(str(event.get("kind") or "")) for event in daily_events),
        "recoveries": sum(event_kind_is_recovery(str(event.get("kind") or "")) for event in daily_events),
        "latest_event_at_ts": max(timestamps, default=None),
    }
