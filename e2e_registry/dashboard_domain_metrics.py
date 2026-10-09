# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain primary and subcheck observations used by the registry dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.cycle_values import required_float
from domain_checks.history import compute_availability, latency_percentile_ms, window_samples

from .dashboard_records import object_or_empty, required_object
from .dashboard_values import safe_float, safe_int, safe_timestamp

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from domain_checks.config_values import ConfigValue
    from domain_checks.cycle_values import NumericInput
    from domain_checks.event_bus_delivery import JsonValue
    from domain_checks.history import Sample

    from .dashboard_records import Record

_HTTP_INDEX = 2
_BROWSER_INDEX = 3
_STATUS_INDEX = 4
_MIN_RESULT_FIELDS = 2


def sample_observation(values: Sequence[NumericInput]) -> Record:
    """Expose present sample fields without manufacturing latency or status.

    Returns:
        The five named primary observation fields, including short-row fallback.
    """
    return {
        "ts": safe_float(values[0]) if values else None,
        "ok": bool(values[1]) if len(values) >= _MIN_RESULT_FIELDS else None,
        "http_ms": safe_float(values[_HTTP_INDEX]) if len(values) > _HTTP_INDEX else None,
        "browser_ms": safe_float(values[_BROWSER_INDEX]) if len(values) > _BROWSER_INDEX else None,
        "status_code": safe_int(values[_STATUS_INDEX]) if len(values) > _STATUS_INDEX else None,
    }


def subcheck_field(state: Mapping[str, JsonValue], section: str, field: str, domain: str) -> ConfigValue:
    """Read the original section/field mapping, preserving malformed-section failures.

    Returns:
        The stored domain value without boolean or timestamp coercion.
    """
    values = required_object(state.get(section, {})).get(field, {})
    return required_object(values or {}).get(domain)


def primary_observation(items: list[Sample], *, state: Mapping[str, JsonValue], domain: str) -> Record:
    """Prefer the final sample and use last_ok only when the sample lacks a result.

    Returns:
        Primary time, status and latency fields; unavailable values remain None.
    """
    sample = items[-1] if items else None
    values = sample if isinstance(sample, list) else []
    last_ok = object_or_empty(state.get("last_ok"))
    outcome = None
    if len(values) >= _MIN_RESULT_FIELDS:
        outcome = bool(values[1])
    elif domain in last_ok:
        outcome = bool(last_ok.get(domain))
    observation = sample_observation(values)
    observation["ok"] = outcome
    return observation


def day_metrics(items: list[Sample], *, performance: Record, now_ts: float) -> Record:
    """Keep the existing 24-hour availability, percentile and slow-count algorithms.

    Returns:
        Availability, latency and threshold records in their original shape.
    """
    http_max = safe_float(performance.get("http_elapsed_ms_max"))
    browser_max = safe_float(performance.get("browser_elapsed_ms_max"))
    window = window_samples(items, since_ts=float(now_ts) - 86400.0) if items else []
    total, healthy, percentage = compute_availability(window)
    http_p95 = latency_percentile_ms(window, field="http_elapsed_ms", percentile=95.0) if window else None
    browser_p95 = latency_percentile_ms(window, field="browser_elapsed_ms", percentile=95.0) if window else None
    http_slow = _slow_count(window, index=2, threshold=http_max)
    browser_slow = _slow_count(window, index=3, threshold=browser_max)
    return {
        "availability_24h": {"total": int(total), "ok": int(healthy), "ok_pct": percentage},
        "latency_24h": {"http_p95_ms": http_p95, "browser_p95_ms": browser_p95},
        "slow_24h": {"http_count": http_slow, "browser_count": browser_slow,
                     "http_threshold_ms": http_max, "browser_threshold_ms": browser_max},
    }


def _slow_count(samples: list[Sample], *, index: int, threshold: float | None) -> int | None:
    if not samples or threshold is None:
        return None
    count = 0
    for sample in samples:
        if len(sample) > index and sample[index] is not None and required_float(sample[index]) > float(threshold):
            count += 1
    return count


def effective_observation(primary: Record, *, state: Mapping[str, JsonValue], domain: str) -> tuple[Record, Record]:
    """Combine only explicit primary/API/synthetic failures and preserve their identity.

    Returns:
        The effective last observation and the separately retained subcheck values.
    """
    synthetic_ok = subcheck_field(state, "synthetic", "last_ok", domain)
    api_ok = subcheck_field(state, "api_contract", "last_ok", domain)
    synthetic_ts = safe_timestamp(subcheck_field(state, "synthetic", "last_run_ts", domain))
    api_ts = safe_timestamp(subcheck_field(state, "api_contract", "last_run_ts", domain))
    failures: list[ConfigValue] = []
    for source, outcome in (("primary", primary["ok"]), ("api_contract", api_ok), ("synthetic", synthetic_ok)):
        if outcome is False:
            failures.append(source)
    observed_times = (safe_float(primary["ts"]), api_ts, synthetic_ts)
    timestamps = [value for value in observed_times if value is not None]
    effective_code = primary["status_code"] if primary["ok"] is False or not failures else None
    last: Record = {
        "ts": max(timestamps) if timestamps else None, "primary_ts": primary["ts"],
        "ok": False if failures else primary["ok"], "primary_ok": primary["ok"], "failure_sources": failures,
        "http_ms": primary["http_ms"], "browser_ms": primary["browser_ms"], "status_code": effective_code,
        "primary_status_code": primary["status_code"],
    }
    subchecks: Record = {"synthetic_ok": synthetic_ok, "api_ok": api_ok, "synthetic_ts": synthetic_ts, "api_ts": api_ts}
    return last, subchecks


def subcheck_summaries(values: Record, *, state: Mapping[str, JsonValue], domain: str) -> Record:
    """Read streaks at the original response-building boundary, without resetting them.

    Returns:
        Synthetic, web-vitals and API records; raw web-vitals time is preserved.
    """
    return {
        "synthetic": {
            "last_ok": values["synthetic_ok"], "fail_streak": subcheck_field(state, "synthetic", "fail_streak", domain),
            "success_streak": subcheck_field(state, "synthetic", "success_streak", domain),
            "last_run_ts": values["synthetic_ts"],
        },
        "web_vitals": {
            "last_ok": subcheck_field(state, "web_vitals", "last_ok", domain),
            "fail_streak": subcheck_field(state, "web_vitals", "fail_streak", domain),
            "success_streak": subcheck_field(state, "web_vitals", "success_streak", domain),
            "last_run_ts": subcheck_field(state, "web_vitals", "last_run_ts", domain),
        },
        "api_contract": {
            "last_ok": values["api_ok"], "fail_streak": subcheck_field(state, "api_contract", "fail_streak", domain),
            "success_streak": subcheck_field(state, "api_contract", "success_streak", domain),
            "last_run_ts": values["api_ts"],
        },
    }
