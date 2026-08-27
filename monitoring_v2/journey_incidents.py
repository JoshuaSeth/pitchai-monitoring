# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compose retained failing journeys into actionable incident contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .json_types import float_value, int_value, object_list, text_value

if TYPE_CHECKING:
    from .json_types import JsonObject


def build_journey_incidents(journeys: JsonObject) -> list[JsonObject]:
    """Return an incident for each currently failing retained journey."""
    incidents: list[JsonObject] = []
    for journey in object_list(journeys.get("items")):
        if text_value(journey.get("status")) != "failing":
            continue
        test_id = text_value(journey.get("test_id"))
        incidents.append(
            {
                "incident_id": f"e2e_failure:{test_id}",
                "kind": "e2e_failure",
                "severity": "warning",
                "title": f"E2E: {text_value(journey.get('test_name'), default='Unnamed journey')}",
                "detail": "A retained user-critical journey is failing.",
                "current_status": "failing",
                "affected_check": text_value(journey.get("test_kind"), default="end-to-end journey"),
                "affected_service": text_value(journey.get("host"), default="unknown service"),
                "owner_project": text_value(journey.get("owner_project"), default="Unconfigured"),
                "first_seen_at_ts": float_value(journey.get("last_fail_at_ts")),
                "latest_seen_at_ts": float_value(journey.get("last_finished_at_ts")),
                "last_successful_sample": {"observed_at_ts": float_value(journey.get("last_ok_at_ts"))},
                "trend": {
                    "direction": "degrading",
                    "observations": int_value(journey.get("fail_streak")) or 0,
                    "points": [],
                },
                "alert_policy": {
                    "channel": "Telegram",
                    "enabled": True,
                    "mode": "E2E failure policy",
                },
                "suggested_next_action": (
                    "Reproduce the first failed journey step and inspect the linked dispatch evidence before changing "
                    "production."
                ),
                "evidence_state": "available",
            },
        )
    return incidents
