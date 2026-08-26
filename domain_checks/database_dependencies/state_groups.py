# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deduplicate database dependency alerts at app-group level."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from domain_checks.monitoring_contracts.json_types import bool_value, float_value, text_value

if TYPE_CHECKING:
    from domain_checks.monitoring_contracts.json_types import JsonObject


def _migration_group_state(
    group: str,
    items: list[JsonObject],
    previous_dependencies: dict[str, JsonObject],
) -> JsonObject:
    prior_members = [previous_dependencies.get(text_value(item.get("dependency_id")), {}) for item in items]
    was_down = any(
        text_value(item.get("status")) == "down" and bool_value(item.get("telegram_alert_enabled")) is True
        for item in prior_members
    )
    opened_candidates: list[float] = []
    for item in prior_members:
        value = float_value(item.get("failure_started_at_ts"))
        if value is not None:
            opened_candidates.append(value)
    return {
        "alert_group": group,
        "status": "down" if was_down else "healthy",
        "opened_at_ts": min(opened_candidates) if opened_candidates and was_down else None,
        "last_transition_at_ts": None,
        "last_alert_at_ts": None,
    }


def _alert_member(item: JsonObject) -> JsonObject:
    return {
        "dependency_id": item.get("dependency_id"),
        "affected_app": item.get("affected_app"),
        "container": item.get("container"),
        "owner_project": item.get("owner_project"),
        "database_dependency": item.get("database_dependency"),
        "traffic_slot": item.get("traffic_slot"),
        "traffic_weight": item.get("traffic_weight"),
        "failure_class": item.get("failure_class"),
        "failure_phase": item.get("failure_phase"),
        "credential_state": item.get("credential_state"),
        "last_success_at_ts": item.get("last_success_at_ts"),
        "failure_started_at_ts": item.get("failure_started_at_ts"),
        "likely_fix_path": item.get("likely_fix_path"),
        "sanitized_error_excerpt": item.get("sanitized_error_excerpt"),
    }


def _group_alert(group: str, items: list[JsonObject], *, observed_at_ts: float) -> JsonObject:
    affected = [item for item in items if bool_value(item.get("telegram_alert_eligible")) is True]
    return {
        "alert_id": f"{group}:{observed_at_ts}",
        "alert_group": group,
        "observed_at_ts": observed_at_ts,
        "members": [_alert_member(item) for item in affected],
    }


def _reduce_group(
    group: str,
    items: list[JsonObject],
    previous: JsonObject,
    *,
    generated_at_ts: float,
) -> tuple[JsonObject, JsonObject | None]:
    previous_status = text_value(previous.get("status"), default="healthy")
    enabled = [item for item in items if bool_value(item.get("telegram_alert_enabled")) is True]
    has_new_down = any(bool_value(item.get("telegram_alert_eligible")) is True for item in enabled)
    all_recovered = bool(enabled) and all(text_value(item.get("status")) == "healthy" for item in enabled)
    if previous_status == "down":
        status = "healthy" if all_recovered else "down"
    else:
        status = "down" if has_new_down else "healthy"
    transitioned = status != previous_status
    opened_at_ts = float_value(previous.get("opened_at_ts"))
    if status == "down" and previous_status != "down":
        opened_at_ts = generated_at_ts
    elif status == "healthy":
        opened_at_ts = None
    failing_member_count = 0
    for item in items:
        if bool_value(item.get("observed_ok")) is False:
            failing_member_count += 1
    group_state: JsonObject = {
        "alert_group": group,
        "status": status,
        "member_count": len(items),
        "enabled_member_count": len(enabled),
        "failing_member_count": failing_member_count,
        "opened_at_ts": opened_at_ts,
        "last_transition_at_ts": (
            generated_at_ts if transitioned else float_value(previous.get("last_transition_at_ts"))
        ),
        "last_alert_at_ts": (
            generated_at_ts
            if status == "down" and previous_status != "down"
            else float_value(previous.get("last_alert_at_ts"))
        ),
    }
    alert = (
        _group_alert(group, items, observed_at_ts=generated_at_ts)
        if status == "down" and previous_status != "down"
        else None
    )
    return group_state, alert


def reduce_alert_groups(
    *,
    dependencies: list[JsonObject],
    prior_groups: dict[str, JsonObject],
    prior_dependencies: dict[str, JsonObject],
    pending_alerts: list[JsonObject],
    generated_at_ts: float,
) -> tuple[list[JsonObject], list[JsonObject]]:
    """Reduce group transitions while preserving undelivered alerts.

    Returns:
        Current alert-group state and the updated pending-alert queue.
    """
    grouped: defaultdict[str, list[JsonObject]] = defaultdict(list)
    for item in dependencies:
        grouped[text_value(item.get("alert_group"))].append(item)
    pending_groups: set[str] = set()
    for item in pending_alerts:
        group = text_value(item.get("alert_group"))
        if group:
            pending_groups.add(group)
    alert_groups: list[JsonObject] = []
    for group in sorted(grouped):
        previous = prior_groups.get(group)
        if previous is None:
            previous = _migration_group_state(group, grouped[group], prior_dependencies)
        group_state, alert = _reduce_group(
            group,
            grouped[group],
            previous,
            generated_at_ts=generated_at_ts,
        )
        alert_groups.append(group_state)
        if alert is not None and group not in pending_groups:
            pending_alerts.append(alert)
            pending_groups.add(group)
    current_groups = set(grouped)
    for group, group_state in sorted(prior_groups.items()):
        if group not in current_groups and text_value(group_state.get("status")) == "down":
            alert_groups.append(group_state)
    return alert_groups, pending_alerts
