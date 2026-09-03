# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict recovery adapter for proven scheduler placement success."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from .domain_event_models import DomainTransitionEvent
from .json_types import normalized_object_reference, text_value
from .scheduler_incident_event import placement_failure_event, required_text, required_timestamp

if TYPE_CHECKING:
    from .json_types import JsonObject

_MAX_STORAGE_PATH = 512


def placement_recovery_event(recovery: JsonObject) -> DomainTransitionEvent:
    """Convert one completed-create proof to a linked monitoring recovery.

    Returns:
        An immutable recovery transition for the exact prior incident.

    Raises:
        TypeError: If the recovery proof is malformed.
        ValueError: If the proof does not follow its prior failure.
    """
    if recovery.get("signal_schema_version") != 1 or recovery.get("kind") != "new_lane_placement_recovered":
        message = "scheduler incident feed returned an unsupported recovery signal"
        raise ValueError(message)
    occurred_at = required_timestamp(recovery, "occurred_at")
    project_key = required_text(recovery, "project_key", limit=256)
    origin_branch = required_text(recovery, "origin_branch", limit=512)
    assigned_cell_slug = required_text(recovery, "assigned_cell_slug", limit=63)
    command_id = required_text(recovery, "command_id", limit=64)
    parsed_command_id = UUID(command_id)
    audit_event_id = recovery.get("audit_event_id")
    if isinstance(audit_event_id, bool) or not isinstance(audit_event_id, int) or audit_event_id < 1:
        message = "scheduler incident recovery audit_event_id is invalid"
        raise TypeError(message)
    storage_value = recovery.get("new_lane_storage_root")
    storage_root = text_value(storage_value)
    if storage_value is not None and (not storage_root.strip() or len(storage_root) > _MAX_STORAGE_PATH):
        message = "scheduler incident recovery storage root is invalid"
        raise TypeError(message)

    prior_value = recovery.get("prior_failure")
    if not isinstance(prior_value, dict):
        message = "scheduler incident recovery prior_failure is invalid"
        raise TypeError(message)
    prior_failure = normalized_object_reference(prior_value)
    prior_project_key = required_text(prior_failure, "project_key", limit=256)
    if prior_project_key != project_key:
        message = "scheduler incident recovery project does not match its prior failure"
        raise ValueError(message)
    prior_audit_event_id = prior_failure.get("audit_event_id")
    if isinstance(prior_audit_event_id, bool) or not isinstance(prior_audit_event_id, int) or prior_audit_event_id < 1:
        message = "scheduler incident recovery prior audit_event_id is invalid"
        raise TypeError(message)
    failure_event = placement_failure_event(prior_failure)
    recovery_timestamp = datetime.fromisoformat(occurred_at).timestamp()
    if failure_event.occurred_at >= recovery_timestamp:
        message = "scheduler incident recovery does not follow its prior failure"
        raise ValueError(message)

    details = dict(failure_event.details)
    for failure_only_field in ("reason", "error", "reasons", "evidence", "repair_dispatch"):
        details.pop(failure_only_field, None)
    selected_storage = storage_root.strip() if storage_root else "not reported"
    details.update(
        cast(
            "JsonObject",
            {
                "severity": "info",
                "reason": "completed central agent.create proves safe new-lane placement recovered",
                "recovered_at_ts": recovery_timestamp,
                "evidence": [
                    (
                        f"completed agent.create command={parsed_command_id} project={project_key} "
                        f"configured_base={origin_branch}"
                    ),
                    f"assigned cell={assigned_cell_slug} selected_new_lane_storage={selected_storage}",
                    f"prior terminal placement failure audit_event_id={prior_audit_event_id}",
                ],
                "repair_dispatch": (
                    "Verify the recovered placement remains healthy and reconcile its existing incident lane."
                ),
                "incident_update": "recovered",
            },
        ),
    )
    return DomainTransitionEvent(
        kind="production_recovered",
        occurred_at=recovery_timestamp,
        details=details,
    )
