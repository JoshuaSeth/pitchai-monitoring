# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compose the production monitoring dashboard from retained source data."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from monitoring_contracts.json_types import (
    float_value,
    int_value,
    json_object,
    normalize_json,
    object_list,
    optional_object,
    text_value,
)
from monitoring_contracts.safe_evidence import safe_public_url, safe_text_excerpt

from .databases import load_database_dashboard
from .event_analysis import safe_events
from .incidents import IncidentSources, build_incidents
from .infrastructure import build_infrastructure
from .journeys import build_journeys
from .legacy import legacy_dashboard
from .reliability import build_reliability

if TYPE_CHECKING:
    from monitoring_contracts.json_types import (
        JsonObject,
        JsonValue,
    )

    from .legacy import MonitorData

_LEGACY_BUILD = legacy_dashboard.build_dashboard_summary


def _safe_diagnostic_rows(value: JsonValue | object) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for raw in object_list(value)[-80:]:
        row: JsonObject = {}
        for key in ("ts", "created_at_ts"):
            timestamp = float_value(raw.get(key))
            if timestamp is not None:
                row[key] = timestamp
        for key in ("queue_state", "state_key", "title"):
            cleaned = safe_text_excerpt(raw.get(key), max_chars=160)
            if cleaned:
                row[key] = cleaned
        for key in ("agent_message", "error_message"):
            cleaned = safe_text_excerpt(raw.get(key), max_chars=500)
            if cleaned:
                row[key] = cleaned
        ui_url = safe_public_url(raw.get("ui_url"))
        if ui_url and ui_url.startswith("https://dispatch.pitchai.net/"):
            row["ui_url"] = ui_url
        rows.append(row)
    return rows


def _freshness_without_invented_interval(summary: JsonObject, config: JsonObject) -> None:
    freshness = optional_object(summary.get("freshness"))
    interval = int_value(config.get("interval_seconds"))
    if interval is not None and interval > 0:
        return
    observed_at = float_value(freshness.get("state_updated_at_ts"))
    summary["freshness"] = {
        "status": "unknown",
        "state_updated_at_ts": observed_at,
        "age_seconds": freshness.get("age_seconds"),
        "interval_seconds": None,
        "stale_after_seconds": None,
        "source": text_value(freshness.get("source"), default="unavailable"),
    }


def _e2e_compatibility(journeys: JsonObject) -> JsonObject:
    return {
        "status": journeys.get("status"),
        "data_state": journeys.get("data_state"),
        "total_tests": journeys.get("total"),
        "passing_tests": journeys.get("passing"),
        "failing_tests": journeys.get("failing"),
        "stale_tests": journeys.get("stale"),
        "infra_degraded_tests": journeys.get("infra_degraded"),
        "never_run_tests": journeys.get("never_run"),
        "unknown_tests": journeys.get("unknown"),
        "disabled_tests": journeys.get("disabled"),
        "latest_run_at_ts": journeys.get("latest_run_at_ts"),
        "latest_run_age_seconds": journeys.get("latest_run_age_seconds"),
        "problems": [
            item for item in object_list(journeys.get("items")) if text_value(item.get("status")) == "failing"
        ],
        "journeys": journeys.get("items"),
    }


def build_dashboard_summary(
    *,
    data: MonitorData,
    now_ts: float,
    e2e_status_summary: JsonObject | None,
    e2e_dispatch_runs: list[JsonObject] | None,
) -> JsonObject:
    """Enrich the proven legacy summary with actionable tabs and safe evidence.

    Returns:
        The backward-compatible summary plus actionable dashboard contracts.
    """
    summary = json_object(
        cast(
            "JsonValue",
            _LEGACY_BUILD(
                data=data,
                now_ts=now_ts,
                e2e_status_summary=e2e_status_summary,
                e2e_dispatch_runs=e2e_dispatch_runs,
            ),
        ),
    )
    state = json_object(cast("JsonValue", data.state))
    config = json_object(cast("JsonValue", data.config))
    _freshness_without_invented_interval(summary, config)
    events = safe_events(state.get("events"))
    domains = object_list(summary.get("domains"))
    journeys = build_journeys(
        e2e_status=e2e_status_summary,
        dispatch_runs=e2e_dispatch_runs,
        domains=domains,
        now_ts=now_ts,
    )
    infrastructure = build_infrastructure(state=state, config=config, now_ts=now_ts)
    reliability = build_reliability(
        summary=summary,
        state=state,
        config=config,
        events=events,
        now_ts=now_ts,
    )
    databases = load_database_dashboard(now_ts=now_ts)
    incidents = build_incidents(
        IncidentSources(
            summary=summary,
            state=state,
            events=events,
            journeys=journeys,
            databases=databases,
            now_ts=now_ts,
        ),
    )
    summary["e2e"] = _e2e_compatibility(journeys)
    summary["incidents"] = normalize_json(incidents)
    summary["events"] = normalize_json(events)
    summary["dashboards"] = json_object({
        "infrastructure": infrastructure,
        "reliability": reliability,
        "journeys": journeys,
        "databases": databases,
    })
    dispatch = optional_object(summary.get("dispatch"))
    summary["dispatch"] = json_object({
        "last_by_key": {},
        "recent": _safe_diagnostic_rows(dispatch.get("recent")),
    })
    summary["external_e2e"] = None
    summary["e2e_registry_dispatch"] = normalize_json(_safe_diagnostic_rows(e2e_dispatch_runs))
    summary["state_path"] = "configured monitor state"
    summary["config_path"] = "configured monitor configuration"
    return summary
