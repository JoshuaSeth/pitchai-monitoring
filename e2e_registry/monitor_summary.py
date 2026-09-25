# Copyright (c) 2026 PitchAI. All rights reserved.
"""Composition of the complete operator monitoring dashboard summary."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

from e2e_registry.monitor_domains import summarize_domains
from e2e_registry.monitor_groups import service_health, summarize_domain_groups
from e2e_registry.monitor_health import summarize_daily_status, summarize_e2e, summarize_freshness
from e2e_registry.monitor_incidents import IncidentContext, build_incidents
from e2e_registry.monitor_inventory import normalize_domain_entries
from e2e_registry.monitor_signals import summarize_signals
from e2e_registry.monitor_values import history_range_utc, monitor_mapping, monitor_records

if TYPE_CHECKING:
    from domain_checks.history import Sample
    from e2e_registry.monitor_types import MonitorData, MonitorRecord, MonitorRecords

_DEBOUNCED_SIGNALS = (
    "host_health",
    "performance",
    "slo",
    "red",
    "tls",
    "dns",
    "container_health",
    "proxy",
    "meta",
)


class _DashboardParts(NamedTuple):
    history: dict[str, list[Sample]]
    history_min_ts: float | None
    history_max_ts: float | None
    domains: MonitorRecords
    signals: MonitorRecord
    down_domains: MonitorRecords
    degraded_signals: list[str]
    events: MonitorRecords
    freshness: MonitorRecord
    aggregate_health: MonitorRecord
    domain_groups: MonitorRecords
    e2e: MonitorRecord
    incidents: MonitorRecords


def _history(data: MonitorData) -> dict[str, list[Sample]]:
    history = monitor_mapping(data.state.get("history"))
    return cast("dict[str, list[Sample]]", history)


def _problem_domains(domains: MonitorRecords) -> tuple[MonitorRecords, MonitorRecords]:
    enabled = [domain for domain in domains if not bool(domain.get("disabled"))]
    down = [domain for domain in enabled if monitor_mapping(domain.get("last")).get("ok") is False]
    unknown = [domain for domain in enabled if monitor_mapping(domain.get("last")).get("ok") is None]
    return down, unknown


def _degraded_signals(signals: MonitorRecord) -> list[str]:
    degraded = [
        signal
        for signal in _DEBOUNCED_SIGNALS
        if monitor_mapping(signals.get(signal)).get("last_ok") is False
    ]
    if monitor_mapping(signals.get("browser")).get("degraded_active"):
        degraded.append("browser")
    return degraded


def _inventory_summary(
    *,
    data: MonitorData,
    domains: MonitorRecords,
    domain_groups: MonitorRecords,
    history: dict[str, list[Sample]],
) -> MonitorRecord:
    retired = data.config.get("retired_domains")
    retired_domains = retired if isinstance(retired, list) else []
    inventory = monitor_mapping(data.config.get("inventory"))
    configured_domains: set[str] = set()
    for entry in normalize_domain_entries(data.config.get("domains")):
        domain = entry.get("domain")
        if domain:
            configured_domains.add(str(domain))
    state_domains = set(history) | set(monitor_mapping(data.state.get("last_ok")))
    return {
        "version": inventory.get("version"),
        "reviewed_at": inventory.get("reviewed_at"),
        "active_domains": len(domains),
        "groups": len(domain_groups),
        "retired_domains": len(retired_domains),
        "orphaned_state_domains": len(state_domains - configured_domains),
    }


def _incident_summary(
    *,
    domains: MonitorRecords,
    signals: MonitorRecord,
    freshness: MonitorRecord,
    e2e: MonitorRecord,
) -> tuple[MonitorRecords, list[str], MonitorRecords]:
    down_domains, unknown_domains = _problem_domains(domains)
    degraded_signals = _degraded_signals(signals)
    incidents = build_incidents(
        IncidentContext(
            down_domains=down_domains,
            unknown_domains=unknown_domains,
            degraded_signals=degraded_signals,
            freshness=freshness,
            e2e=e2e,
            signals=signals,
        ),
    )
    return down_domains, degraded_signals, incidents


def _dashboard_parts(
    *,
    data: MonitorData,
    now_ts: float,
    e2e_status_summary: MonitorRecord | None,
) -> _DashboardParts:
    history = _history(data)
    history_min_ts, history_max_ts = history_range_utc(history)
    domains = summarize_domains(data=data, now_ts=now_ts)
    signals = summarize_signals(data=data)
    events = monitor_records(data.state.get("events"))
    freshness = summarize_freshness(data=data, now_ts=now_ts, history_max_ts=history_max_ts)
    domain_groups = summarize_domain_groups(domains=domains, config=data.config)
    e2e = summarize_e2e(e2e_status_summary, now_ts=now_ts)
    down_domains, degraded_signals, incidents = _incident_summary(
        domains=domains,
        signals=signals,
        freshness=freshness,
        e2e=e2e,
    )
    return _DashboardParts(
        history=history,
        history_min_ts=history_min_ts,
        history_max_ts=history_max_ts,
        domains=domains,
        signals=signals,
        down_domains=down_domains,
        degraded_signals=degraded_signals,
        events=events,
        freshness=freshness,
        aggregate_health=service_health(domains),
        domain_groups=domain_groups,
        e2e=e2e,
        incidents=incidents,
    )


def build_dashboard_summary(
    *,
    data: MonitorData,
    now_ts: float,
    e2e_status_summary: MonitorRecord | None,
    e2e_dispatch_runs: MonitorRecords | None,
) -> MonitorRecord:
    """Build the complete operator dashboard payload from normalized inputs.

    Returns:
        The JSON-compatible dashboard summary.
    """
    parts = _dashboard_parts(
        data=data,
        now_ts=float(now_ts),
        e2e_status_summary=e2e_status_summary,
    )
    return cast(
        "MonitorRecord",
        {
            "ok": True,
            "generated_at_ts": float(now_ts),
            "state_path": data.state_path,
            "config_path": data.config_path,
            "loaded_at_ts": float(data.loaded_at_ts),
            "error": data.state_error,
            "history_range": {"min_ts": parts.history_min_ts, "max_ts": parts.history_max_ts},
            "freshness": parts.freshness,
            "service_health": parts.aggregate_health,
            "domain_groups": parts.domain_groups,
            "inventory": _inventory_summary(
                data=data,
                domains=parts.domains,
                domain_groups=parts.domain_groups,
                history=parts.history,
            ),
            "e2e": parts.e2e,
            "incidents": parts.incidents,
            "daily_status": summarize_daily_status(
                domains=parts.domains,
                events=parts.events,
                open_problem_count=len(parts.incidents),
                now_ts=float(now_ts),
            ),
            "domains": parts.domains,
            "signals": parts.signals,
            "warnings": {
                "down_domains": [domain.get("domain") for domain in parts.down_domains],
                "degraded_signals": parts.degraded_signals,
            },
            "dispatch": {
                "last_by_key": monitor_mapping(data.state.get("dispatch_last")),
                "recent": monitor_records(data.state.get("dispatch_history")),
            },
            "events": parts.events,
            "external_e2e": e2e_status_summary,
            "e2e_registry_dispatch": e2e_dispatch_runs or [],
        },
    )
