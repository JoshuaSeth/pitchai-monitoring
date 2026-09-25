# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed in-memory state for monitor cycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_checks.history import SampleHistory, coerce_history
from domain_checks.monitor_state import update_effective_ok
from domain_checks.monitor_value_collections import (
    bool_dict,
    bounded_objects,
    float_dict,
    int_dict,
    object_dict,
    signal_history,
    string_list_dict,
)
from domain_checks.monitor_values import bool_value, float_value, int_value, json_object

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue


@dataclass
class SignalStatus:
    """Debounced status and optional last execution timestamp."""

    last_ok: bool = True
    fail_streak: int = 0
    success_streak: int = 0
    last_run_ts: float = 0.0

    def observe(self, *, observed_ok: bool, down_after: int, up_after: int) -> tuple[bool, bool]:
        """Apply an observation and return down/recovery transition flags.

        Returns:
            The down and recovery transition flags.
        """
        previous = self.last_ok
        self.last_ok, self.fail_streak, self.success_streak, alerted_down = update_effective_ok(
            prev_effective_ok=previous,
            observed_ok=observed_ok,
            fail_streak=self.fail_streak,
            success_streak=self.success_streak,
            down_after_failures=down_after,
            up_after_successes=up_after,
        )
        return alerted_down, (not previous) and self.last_ok


@dataclass
class PerDomainStatus:
    """Debounce and cadence state keyed by domain."""

    last_ok: dict[str, bool]
    fail_streak: dict[str, int]
    success_streak: dict[str, int]
    last_run_ts: dict[str, float]

    @classmethod
    def from_json(cls, value: JsonValue) -> PerDomainStatus:
        """Decode one persisted per-domain status section.

        Returns:
            The decoded per-domain status.
        """
        section = json_object(value)
        return cls(
            last_ok=bool_dict(section.get("last_ok")),
            fail_streak=int_dict(section.get("fail_streak")),
            success_streak=int_dict(section.get("success_streak")),
            last_run_ts=float_dict(section.get("last_run_ts")),
        )

    def observe(self, domain: str, *, observed_ok: bool, down_after: int, up_after: int) -> tuple[bool, bool]:
        """Apply one domain observation and return down/recovery flags.

        Returns:
            The down and recovery transition flags.
        """
        previous = self.last_ok.get(domain, True)
        effective, failures, successes, alerted_down = update_effective_ok(
            prev_effective_ok=previous,
            observed_ok=observed_ok,
            fail_streak=self.fail_streak.get(domain, 0),
            success_streak=self.success_streak.get(domain, 0),
            down_after_failures=down_after,
            up_after_successes=up_after,
        )
        self.last_ok[domain] = effective
        self.fail_streak[domain] = failures
        self.success_streak[domain] = successes
        return alerted_down, (not previous) and effective

    def remove(self, domain: str) -> None:
        """Remove all state for a disabled domain."""
        for mapping in (self.last_ok, self.fail_streak, self.success_streak, self.last_run_ts):
            mapping.pop(domain, None)


@dataclass
class StateCollections:
    """Bounded histories, event records, and family baselines."""

    signal_history: dict[str, list[list[JsonValue]]]
    dispatch_history: list[JsonObject]
    dispatch_last: dict[str, JsonObject]
    events: list[JsonObject]
    event_bus_outbox: JsonValue
    dns_last_ips: dict[str, list[str]]
    restart_counts: dict[str, int]


@dataclass
class StateMetadata:
    """Host, browser, and persistence health metadata."""

    host_last_snapshot: JsonObject
    browser: JsonObject
    host_cpu_prev_total: int
    host_cpu_prev_idle: int
    state_write_fail_streak: int


@dataclass
class RuntimeState:
    """Complete mutable state shared across monitor cycle families."""

    domains: PerDomainStatus
    history: SampleHistory
    global_signals: dict[str, SignalStatus]
    per_domain_signals: dict[str, PerDomainStatus]
    collections: StateCollections
    metadata: StateMetadata


def _signal(value: JsonValue) -> SignalStatus:
    section = json_object(value)
    return SignalStatus(
        last_ok=bool_value(section.get("last_ok"), default=True),
        fail_streak=int_value(section.get("fail_streak")),
        success_streak=int_value(section.get("success_streak")),
        last_run_ts=float_value(section.get("last_run_ts")),
    )


def runtime_state(payload: JsonObject) -> RuntimeState:
    """Decode the canonical persisted payload into mutable typed state.

    Returns:
        The decoded mutable runtime state.
    """
    dns = json_object(payload.get("dns"))
    container = json_object(payload.get("container_health"))
    host = json_object(payload.get("host_health"))
    meta = json_object(payload.get("meta"))
    browser: JsonObject = {
        "degraded_active": bool_value(payload.get("browser_degraded_active"), default=False),
        "first_seen_ts": float_value(payload.get("browser_degraded_first_seen_ts")),
        "last_notice_ts": float_value(payload.get("browser_degraded_last_notice_ts")),
        "recover_streak": 0,
        "launch_fail_count": 0,
        "launch_next_try_ts": 0.0,
        "launch_last_error": payload.get("browser_launch_last_error"),
    }
    global_names = ("host_health", "performance", "slo", "tls", "dns", "red", "container_health", "proxy", "meta")
    per_domain_names = ("synthetic", "web_vitals", "api_contract")
    return RuntimeState(
        domains=PerDomainStatus.from_json({
            "last_ok": payload.get("last_ok"),
            "fail_streak": payload.get("fail_streak"),
            "success_streak": payload.get("success_streak"),
        }),
        history=SampleHistory(coerce_history(payload.get("history"))),
        global_signals={name: _signal(payload.get(name)) for name in global_names},
        per_domain_signals={name: PerDomainStatus.from_json(payload.get(name)) for name in per_domain_names},
        collections=StateCollections(
            signal_history=signal_history(payload.get("signal_history")),
            dispatch_history=bounded_objects(payload.get("dispatch_history"), max_items=1000),
            dispatch_last=object_dict(payload.get("dispatch_last")),
            events=bounded_objects(payload.get("events"), max_items=5000),
            event_bus_outbox=payload.get("event_bus_outbox", []),
            dns_last_ips=string_list_dict(dns.get("last_ips")),
            restart_counts=int_dict(container.get("restart_counts")),
        ),
        metadata=StateMetadata(
            host_last_snapshot=json_object(payload.get("host_last_snapshot")),
            browser=browser,
            host_cpu_prev_total=int_value(host.get("cpu_prev_total")),
            host_cpu_prev_idle=int_value(host.get("cpu_prev_idle")),
            state_write_fail_streak=int_value(meta.get("state_write_fail_streak")),
        ),
    )
