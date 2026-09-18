# Copyright (c) 2026 PitchAI. All rights reserved.
"""Critical database transition contract for the native Events Inbox."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .json_types import (
    bool_value,
    float_value,
    json_object,
    normalize_json,
    object_list,
    text_value,
    value_list,
)

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject

_DASHBOARD_URL = "https://monitoring.pitchai.net/dashboard#databases"
_MAX_EVIDENCE_ITEMS = 20


@dataclass(frozen=True)
class DatabaseIncidentEvent:
    """One durable critical database transition to enqueue."""

    kind: str
    occurred_at: float
    details: JsonObject


def database_transition_events(
    *,
    previous: JsonObject,
    updated: JsonObject,
) -> tuple[DatabaseIncidentEvent, ...]:
    """Return only newly opened or recovered alertable database groups.

    Returns:
        Critical transition events derived from the same debounced group state
        that governs private Telegram alerts.
    """
    prior_groups = _groups_by_id(previous)
    current_groups = _groups_by_id(updated)
    current_dependencies = object_list(updated.get("dependencies"))
    events: list[DatabaseIncidentEvent] = []
    generated_at = float_value(updated.get("generated_at_ts")) or 0.0
    for group, current in sorted(current_groups.items()):
        prior_status = text_value(prior_groups.get(group, {}).get("status"), default="healthy")
        status = text_value(current.get("status"), default="healthy")
        if prior_status != "down" and status == "down":
            members = _group_members(current_dependencies, group=group, down_only=True)
            if members:
                events.append(
                    _database_event(
                        kind="database_down",
                        group=group,
                        members=members,
                        occurred_at=_transition_timestamp(current, fallback=generated_at),
                        recovered=False,
                    ),
                )
        elif prior_status == "down" and status == "healthy":
            members = _group_members(current_dependencies, group=group, down_only=False)
            if members:
                events.append(
                    _database_event(
                        kind="database_recovered",
                        group=group,
                        members=members,
                        occurred_at=_transition_timestamp(current, fallback=generated_at),
                        recovered=True,
                    ),
                )
    return tuple(events)


def _groups_by_id(state: JsonObject) -> dict[str, JsonObject]:
    groups: dict[str, JsonObject] = {}
    for item in object_list(state.get("alert_groups")):
        group = text_value(item.get("alert_group"))
        if group:
            groups[group] = item
    return groups


def _group_members(
    dependencies: list[JsonObject],
    *,
    group: str,
    down_only: bool,
) -> list[JsonObject]:
    grouped = (item for item in dependencies if text_value(item.get("alert_group")) == group)
    enabled = (item for item in grouped if bool_value(item.get("telegram_alert_enabled")) is True)
    if down_only:
        eligible = (item for item in enabled if bool_value(item.get("telegram_alert_eligible")) is True)
        members = list(eligible)
    else:
        members = list(enabled)
    return sorted(members, key=lambda item: text_value(item.get("dependency_id")))


def _database_event(
    *,
    kind: str,
    group: str,
    members: list[JsonObject],
    occurred_at: float,
    recovered: bool,
) -> DatabaseIncidentEvent:
    material = _fingerprint_material(group=group, members=members, recovered=recovered)
    owners = _unique_text(members, "owner_project")
    apps = _unique_text(members, "affected_app")
    domains = _unique_list_text(members, "domains")
    fix_paths = _unique_text(members, "likely_fix_path")
    raw_details = {
        "service": "database-dependency-monitor",
        "site": group,
        "project_group": group,
        "customer_group": group,
        "target_environment": "production",
        "incident_key": f"database:{group}",
        "incident_fingerprint": _fingerprint(material),
        "severity": "info" if recovered else "critical",
        "alertable": True,
        "critical": True,
        "suppressed": False,
        "synthetic": False,
        "expected_behavior": (
            f"Every critical active production database dependency in {group} must connect "
            "and pass its configured schema, relation, and grant checks."
        )[:500],
        "dashboard_url": _DASHBOARD_URL,
        "affected_apps": normalize_json(apps),
        "domains": normalize_json(domains),
        "evidence": normalize_json(_evidence(members=members, recovered=recovered)),
    }
    details = json_object(cast("JsonInput", raw_details))
    if len(owners) == 1:
        details["owner_project"] = owners[0]
    if fix_paths:
        details["likely_fix_path"] = " | ".join(fix_paths)[:500]
    if not recovered:
        errors = _unique_text(members, "sanitized_error_excerpt")
        if errors:
            details["error"] = " | ".join(errors)[:800]
    return DatabaseIncidentEvent(kind=kind, occurred_at=occurred_at, details=details)


def _fingerprint_material(
    *,
    group: str,
    members: list[JsonObject],
    recovered: bool,
) -> JsonObject:
    if recovered:
        return {"alert_group": group, "state": "recovered"}
    material_members: list[JsonObject] = [
        {
            "dependency_id": text_value(member.get("dependency_id")),
            "failure_class": text_value(member.get("failure_class")),
            "failure_phase": text_value(member.get("failure_phase")),
            "traffic_slot": text_value(member.get("traffic_slot")),
            "error": text_value(member.get("sanitized_error_excerpt"))[:500],
        }
        for member in members
    ]
    material = {
        "alert_group": group,
        "members": normalize_json(cast("JsonInput", material_members)),
        "state": "down",
    }
    return json_object(cast("JsonInput", material))


def _evidence(*, members: list[JsonObject], recovered: bool) -> list[str]:
    if recovered:
        return [
            f"{text_value(member.get('dependency_id'))}: debounced database probe recovered"
            for member in members[:_MAX_EVIDENCE_ITEMS]
        ]
    evidence: list[str] = []
    for member in members:
        dependency = text_value(member.get("dependency_id"), default="unknown dependency")
        failure = text_value(member.get("failure_class"), default="unknown failure")
        phase = text_value(member.get("failure_phase"), default="unknown phase")
        evidence.append(f"{dependency}: {failure} during {phase}"[:240])
    return evidence[:_MAX_EVIDENCE_ITEMS]


def _unique_text(members: list[JsonObject], field: str) -> list[str]:
    values: set[str] = set()
    for member in members:
        value = text_value(member.get(field))
        if value:
            values.add(value)
    return sorted(values, key=str.casefold)


def _unique_list_text(members: list[JsonObject], field: str) -> list[str]:
    values: set[str] = set()
    for member in members:
        for value in value_list(member.get(field)):
            if isinstance(value, str) and value.strip():
                values.add(value.strip())
    return sorted(values, key=str.casefold)


def _transition_timestamp(group: JsonObject, *, fallback: float) -> float:
    return float_value(group.get("last_transition_at_ts")) or fallback


def _fingerprint(material: JsonObject) -> str:
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
