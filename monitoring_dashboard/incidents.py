# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build actionable incident contracts from retained monitoring evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from monitoring_contracts.json_types import (
    bool_value,
    float_value,
    int_value,
    object_list,
    optional_object,
    text_value,
)

from .database_incidents import build_database_incidents
from .domain_incidents import (
    build_domain_incident,
    build_unknown_incident,
)
from .journey_incidents import build_journey_incidents

if TYPE_CHECKING:
    from monitoring_contracts.json_types import (
        JsonObject,
    )

_SIGNAL_LABEL_PAIRS = (
    ("host_health", "Host health"),
    ("performance", "Performance"),
    ("slo", "SLO"),
    ("red", "RED metrics"),
    ("tls", "TLS"),
    ("dns", "DNS"),
    ("container_health", "Container health"),
    ("proxy", "Reverse proxy"),
    ("meta", "Monitor integrity"),
    ("browser", "Browser checks"),
)
_SIGNAL_LABELS = dict(_SIGNAL_LABEL_PAIRS)


@dataclass(frozen=True)
class IncidentSources:
    """Current sanitized inputs used to compose one incident list."""

    summary: JsonObject
    state: JsonObject
    events: list[JsonObject]
    journeys: JsonObject
    databases: JsonObject
    now_ts: float


def _signal_incident(signal: str, value: JsonObject) -> JsonObject:
    observed_at = float_value(value.get("observed_at_ts"))
    fail_streak = int_value(value.get("fail_streak")) or 0
    return {
        "incident_id": f"signal_degraded:{signal}",
        "kind": "signal_degraded",
        "severity": "warning",
        "title": f"{_SIGNAL_LABELS.get(signal, signal.replace('_', ' ').title())} is degraded",
        "detail": f"The retained signal has failed {fail_streak} consecutive monitor cycles.",
        "current_status": "degraded",
        "affected_check": _SIGNAL_LABELS.get(signal, signal),
        "affected_service": "service monitoring host",
        "owner_project": "PitchAI core / monitoring",
        "first_seen_at_ts": observed_at,
        "latest_seen_at_ts": observed_at,
        "observed_at_ts": observed_at,
        "last_successful_sample": None,
        "trend": {"direction": "degrading", "observations": fail_streak, "points": []},
        "alert_policy": {
            "channel": "Telegram",
            "enabled": True,
            "mode": "global signal policy",
        },
        "suggested_next_action": (
            "Inspect retained evidence and the contributing host, proxy, certificate, DNS, or monitor subsystem."
        ),
        "evidence_state": "available" if observed_at is not None else "missing",
    }


def build_incidents(sources: IncidentSources) -> list[JsonObject]:
    """Build every current incident with a stable, disclosure-ready contract.

    Returns:
        Current database, monitor, domain, signal, and journey incidents.
    """
    incidents: list[JsonObject] = []
    incidents.extend(build_database_incidents(sources.databases))
    freshness = optional_object(sources.summary.get("freshness"))
    freshness_status = text_value(freshness.get("status"), default="unknown")
    if freshness_status in {"stale", "unknown"}:
        latest = float_value(freshness.get("state_updated_at_ts"))
        incidents.append(
            {
                "incident_id": "monitor_freshness",
                "kind": "monitor_freshness",
                "severity": "critical" if freshness_status == "stale" else "warning",
                "title": "Monitoring state is stale"
                if freshness_status == "stale"
                else "Monitoring freshness is unavailable",
                "detail": "The minute monitor has not produced a trustworthy current snapshot.",
                "current_status": freshness_status,
                "affected_check": "monitor state writer",
                "affected_service": "service monitoring",
                "owner_project": "PitchAI core / monitoring",
                "latest_seen_at_ts": latest,
                "observed_at_ts": latest,
                "trend": {"direction": "stale", "points": []},
                "alert_policy": {
                    "channel": "Telegram",
                    "enabled": True,
                    "mode": "monitor integrity",
                },
                "suggested_next_action": "Restore fresh monitor state before trusting any downstream incident status.",
                "evidence_state": "available" if latest is not None else "missing",
            },
        )
    for domain in object_list(sources.summary.get("domains")):
        if bool_value(domain.get("disabled")) is True:
            continue
        current = bool_value(optional_object(domain.get("last")).get("ok"))
        if current is False:
            incidents.append(
                build_domain_incident(
                    domain,
                    state=sources.state,
                    events=sources.events,
                    now_ts=sources.now_ts,
                ),
            )
        elif current is None:
            incidents.append(build_unknown_incident(domain))
    signals = optional_object(sources.summary.get("signals"))
    for signal in _SIGNAL_LABELS:
        value = optional_object(signals.get(signal))
        degraded = bool_value(value.get("last_ok")) is False
        if signal == "browser":
            degraded = bool_value(value.get("degraded_active")) is True
        if degraded:
            incidents.append(_signal_incident(signal, value))
    incidents.extend(build_journey_incidents(sources.journeys))
    return incidents
