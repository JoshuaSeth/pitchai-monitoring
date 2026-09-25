# Copyright (c) 2026 PitchAI. All rights reserved.
"""Serialization and bounded-history operations for runtime monitor state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

    from domain_checks.event_bus import EventBusOutbox
    from domain_checks.monitor_runtime_state import PerDomainStatus, RuntimeState, SignalStatus
    from domain_checks.types import JsonObject, JsonValue


def prune_signals(state: RuntimeState, *, before_ts: float) -> None:
    """Remove signal samples older than a timestamp."""
    for key in list(state.collections.signal_history):
        samples = state.collections.signal_history[key]
        retained = list(_recent_samples(samples, before_ts=before_ts))
        if retained:
            state.collections.signal_history[key] = retained
        else:
            del state.collections.signal_history[key]


def _recent_samples(samples: list[list[JsonValue]], *, before_ts: float) -> Iterator[list[JsonValue]]:
    for sample in samples:
        if sample and _sample_ts(sample) >= before_ts:
            yield sample


def _sample_ts(sample: list[JsonValue]) -> float:
    value = sample[0]
    if isinstance(value, bool | int | float | str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _signal_payload(status: SignalStatus, *, timed: bool) -> JsonObject:
    payload: JsonObject = {
        "last_ok": status.last_ok,
        "fail_streak": status.fail_streak,
        "success_streak": status.success_streak,
    }
    if timed:
        payload["last_run_ts"] = status.last_run_ts
    return payload


def _per_domain_payload(status: PerDomainStatus) -> JsonObject:
    return {
        "last_ok": status.last_ok,
        "fail_streak": status.fail_streak,
        "success_streak": status.success_streak,
        "last_run_ts": status.last_run_ts,
    }


def build_state_payload(state: RuntimeState, outbox: EventBusOutbox | None) -> JsonObject:
    """Build the canonical bounded state payload for atomic persistence.

    Returns:
        The canonical JSON-compatible state payload.
    """
    host = state.global_signals["host_health"]
    container = state.global_signals["container_health"]
    meta = state.global_signals["meta"]
    browser = state.metadata.browser
    payload: JsonObject = {
        "version": 6,
        "history_ok_mode": "effective",
        "updated_at": datetime.now(UTC).isoformat(),
        "last_ok": state.domains.last_ok,
        "fail_streak": state.domains.fail_streak,
        "success_streak": state.domains.success_streak,
        "history": cast("JsonValue", dict(state.history)),
        "signal_history": state.collections.signal_history,
        "dispatch_history": state.collections.dispatch_history[-500:],
        "dispatch_last": state.collections.dispatch_last,
        "events": state.collections.events[-2000:],
        "event_bus_outbox": cast("JsonValue", outbox.to_state()) if outbox is not None else [],
        "host_last_snapshot": state.metadata.host_last_snapshot,
        "browser_degraded_active": bool(browser.get("degraded_active")),
        "browser_degraded_first_seen_ts": _number(browser.get("first_seen_ts")),
        "browser_degraded_last_notice_ts": _number(browser.get("last_notice_ts")),
        "browser_launch_last_error": browser.get("launch_last_error"),
        "host_health": {
            **_signal_payload(host, timed=False),
            "cpu_prev_total": state.metadata.host_cpu_prev_total,
            "cpu_prev_idle": state.metadata.host_cpu_prev_idle,
        },
        "performance": _signal_payload(state.global_signals["performance"], timed=False),
        "slo": _signal_payload(state.global_signals["slo"], timed=False),
        "tls": _signal_payload(state.global_signals["tls"], timed=True),
        "dns": {
            **_signal_payload(state.global_signals["dns"], timed=True),
            "last_ips": state.collections.dns_last_ips,
        },
        "red": _signal_payload(state.global_signals["red"], timed=False),
        "synthetic": _per_domain_payload(state.per_domain_signals["synthetic"]),
        "web_vitals": _per_domain_payload(state.per_domain_signals["web_vitals"]),
        "api_contract": _per_domain_payload(state.per_domain_signals["api_contract"]),
        "container_health": {
            **_signal_payload(container, timed=True),
            "restart_counts": state.collections.restart_counts,
        },
        "proxy": _signal_payload(state.global_signals["proxy"], timed=False),
        "meta": {
            **_signal_payload(meta, timed=False),
            "state_write_fail_streak": state.metadata.state_write_fail_streak,
        },
    }
    return payload


def _number(value: JsonValue) -> float:
    return float(value) if isinstance(value, bool | int | float | str) else 0.0
