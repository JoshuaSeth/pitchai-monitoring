# Copyright (c) 2026 PitchAI. All rights reserved.
"""Assemble the retained monitoring dashboard without changing monitor state."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

from .dashboard_data import MonitorData, load_monitor_data
from .dashboard_data import load_json as _load_json
from .dashboard_data import load_yaml as _load_yaml
from .dashboard_domains import summarize_domains
from .dashboard_e2e import summarize_e2e as _summarize_e2e
from .dashboard_health import event_kind_is_problem as _event_kind_is_problem
from .dashboard_health import event_kind_is_recovery as _event_kind_is_recovery
from .dashboard_health import summarize_daily_status as _summarize_daily_status
from .dashboard_health import summarize_domain_groups
from .dashboard_health import summarize_freshness as _summarize_freshness
from .dashboard_health import summarize_service_health as _summarize_service_health
from .dashboard_incidents import build_incidents as _build_incidents
from .dashboard_inventory import normalize_domain_entries as _normalize_domain_entries
from .dashboard_inventory import normalize_domain_groups as _normalize_domain_groups
from .dashboard_records import array_or_empty, object_or_empty, required_object
from .dashboard_signals import SIGNAL_KEYS, summarize_signals
from .dashboard_signals import signal_display_name as _signal_display_name
from .dashboard_timeseries import domain_timeseries, resolve_range, signal_timeseries
from .dashboard_values import downsample as _downsample
from .dashboard_values import history_range_utc as _history_range_utc
from .dashboard_values import parse_range_to_seconds as _parse_range_to_seconds
from .dashboard_values import safe_float as _safe_float
from .dashboard_values import safe_int as _safe_int
from .dashboard_values import safe_timestamp as _safe_timestamp

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue
    from domain_checks.history import Sample

    from .dashboard_records import Record

__all__ = [
    "MonitorData", "_build_incidents", "_downsample", "_event_kind_is_problem", "_event_kind_is_recovery",
    "_history_range_utc", "_load_json", "_load_yaml", "_normalize_domain_entries", "_normalize_domain_groups",
    "_parse_range_to_seconds", "_safe_float", "_safe_int", "_safe_timestamp", "_signal_display_name",
    "_summarize_daily_status", "_summarize_e2e", "_summarize_freshness", "_summarize_service_health",
    "build_dashboard_summary", "domain_timeseries", "load_monitor_data", "resolve_range", "signal_timeseries",
    "summarize_domain_groups", "summarize_domains", "summarize_signals",
]


class _Observations(NamedTuple):
    history: Record
    bounds: tuple[float | None, float | None]
    domains: list[Record]
    signals: Record
    down: list[Record]
    unknown: list[Record]
    degraded: list[str]


def _collect_observations(data: MonitorData, now_ts: float) -> _Observations:
    state = data.state or {}
    history = object_or_empty(state.get("history"))
    min_ts, max_ts = _history_range_utc(cast("dict[str, list[Sample]]", history))
    domains = summarize_domains(data=data, now_ts=float(now_ts))
    signals = summarize_signals(data=data)
    down_domains: list[Record] = []
    unknown_domains: list[Record] = []
    for domain in domains:
        if domain.get("disabled"):
            continue
        outcome = required_object(domain.get("last") or {}).get("ok")
        if outcome is False:
            down_domains.append(domain)
        if outcome is None:
            unknown_domains.append(domain)
    degraded: list[str] = []
    for key in SIGNAL_KEYS:
        value = object_or_empty(signals.get(key))
        if value and value.get("last_ok") is False:
            degraded.append(key)
    if required_object(signals.get("browser", {})).get("degraded_active"):
        degraded.append("browser")
    return _Observations(history, (min_ts, max_ts), domains, signals, down_domains, unknown_domains, degraded)


def _inventory_summary(data: MonitorData, observations: _Observations, groups: list[Record]) -> Record:
    retired = array_or_empty(data.config.get("retired_domains"))
    inventory = object_or_empty(data.config.get("inventory"))
    configured_domains: set[str] = set()
    for entry in _normalize_domain_entries(data.config.get("domains")):
        if str(entry.get("domain") or ""):
            configured_domains.add(str(entry.get("domain") or ""))
    state_domains = set(observations.history) | set(
        required_object((data.state or {}).get("last_ok") or {}, operation="keys"),
    )
    return {
        "version": inventory.get("version"), "reviewed_at": inventory.get("reviewed_at"),
        "active_domains": len(observations.domains), "groups": len(groups), "retired_domains": len(retired),
        "orphaned_state_domains": len(state_domains - configured_domains),
    }


def build_dashboard_summary(
    *, data: MonitorData, now_ts: float, e2e_status_summary: Record | None, e2e_dispatch_runs: list[Record] | None,
) -> Record:
    """Assemble observations, local incidents and counts in the existing phase order.

    Returns:
        The existing operator response, retaining raw dispatch/event references.
    """
    state = data.state or {}
    observations = _collect_observations(data, now_ts)
    events = array_or_empty(state.get("events"))
    events = [event for event in events if isinstance(event, dict)]
    freshness = _summarize_freshness(data=data, now_ts=float(now_ts), history_max_ts=observations.bounds[1])
    service_health = _summarize_service_health(observations.domains)
    groups = summarize_domain_groups(domains=observations.domains, config=data.config or {})
    inventory = _inventory_summary(data, observations, groups)
    e2e = _summarize_e2e(e2e_status_summary, now_ts=float(now_ts))
    incidents = _build_incidents(down_domains=observations.down, unknown_domains=observations.unknown,
                                degraded_signals=observations.degraded, freshness=freshness,
                                e2e=e2e, signals=observations.signals)
    daily = _summarize_daily_status(domains=observations.domains, events=cast("list[Record]", events),
                                   open_problem_count=len(incidents), now_ts=float(now_ts))
    return {
        "ok": True, "generated_at_ts": float(now_ts), "state_path": data.state_path, "config_path": data.config_path,
        "loaded_at_ts": float(data.loaded_at_ts), "error": data.state_error,
        "history_range": {"min_ts": observations.bounds[0], "max_ts": observations.bounds[1]}, "freshness": freshness,
        "service_health": cast("ConfigValue", service_health), "domain_groups": cast("ConfigValue", groups),
        "inventory": inventory,
        "e2e": e2e, "incidents": cast("ConfigValue", incidents), "daily_status": daily,
        "domains": cast("ConfigValue", observations.domains), "signals": observations.signals,
        "warnings": {"down_domains": [domain.get("domain") for domain in observations.down],
                     "degraded_signals": cast("ConfigValue", observations.degraded)},
        "dispatch": {"last_by_key": object_or_empty(state.get("dispatch_last")),
                     "recent": array_or_empty(state.get("dispatch_history"))},
        "events": cast("ConfigValue", events), "external_e2e": e2e_status_summary,
        "e2e_registry_dispatch": cast("ConfigValue", e2e_dispatch_runs or []),
    }
