# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deterministic retained hotpath state for browser-level dashboard proof."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .hotpath_contract_runtime import HOTPATH_TYPES
from .json_types import json_object

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject

_INVENTORY_PATH = Path(__file__).parents[1] / "e2e_registry" / "hotpath_inventory.json"
_TIMESTAMP = 1_777_000_000.0
_SOURCE_SHA = "a" * 40
_DEPLOYED_SHA = "b" * 40
_RECEIPT_SHA = "c" * 64


def _latest_report(lane_id: str) -> JsonInput:
    return {
        "artifact_receipt_sha256": _RECEIPT_SHA,
        "deployed_sha": _DEPLOYED_SHA,
        "duration_seconds": 19.4,
        "event_action": "none",
        "evidence_uri": (
            "s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{lane_id}/{_SOURCE_SHA}/proof.json"
        ),
        "fail_streak": 0,
        "failure_class": None,
        "failure_phase": None,
        "failure_reason": None,
        "occurred_at_ts": _TIMESTAMP - 120,
        "received_at_ts": _TIMESTAMP - 118,
        "report_id": "hotpath-v1-browser-real-result",
        "report_receipt_sha256": _RECEIPT_SHA,
        "run_id": "reminder-browser-real-result",
        "severity": "info",
        "source_sha": _SOURCE_SHA,
        "success": True,
        "success_streak": 2,
    }


def hotpath_dashboard_fixture() -> JsonObject:
    """Build the complete browser fixture with real and synthetic proof.

    Returns:
        The deterministic hotpath projection consumed by headed-browser proof.
    """
    inventory = HOTPATH_TYPES.load_inventory(str(_INVENTORY_PATH))
    lane_count = len(inventory.lanes)
    lanes: list[JsonInput] = []
    for index, lane in enumerate(inventory.lanes):
        lanes.append(
            {
                "age_seconds": 120.0 if index == 0 else None,
                "agent_global_id": lane.agent_global_id,
                "expected_behavior": lane.expected_behavior,
                "lane_id": lane.lane_id,
                "latest_report": _latest_report(lane.lane_id) if index == 0 else None,
                "name": lane.name,
                "project": lane.project,
                "reminder_id": lane.reminder_id,
                "status": "passing" if index == 0 else "never_reported",
                "target_surface": lane.target_surface,
            },
        )
    raw: JsonInput = {
        "canonical_tag": inventory.canonical_tag,
        "counts": {
            "critical": 0,
            "never_reported": lane_count - 1,
            "passing": 1,
            "stale": 0,
            "total": lane_count,
            "warning": 0,
        },
        "event_delivery": {"delivered": 1, "delivering": 0, "pending": 0, "retrying": 0},
        "expected_interval_seconds": inventory.expected_interval_seconds,
        "generated_at_ts": _TIMESTAMP,
        "incident_cooldown_seconds": inventory.incident_cooldown_seconds,
        "inventory_reviewed_at": inventory.reviewed_at,
        "lanes": lanes,
        "schema_version": inventory.schema_version,
        "stale_after_seconds": inventory.stale_after_seconds,
        "status": "attention",
        "synthetic_proofs": [
            {
                "delivery_status": "delivered",
                "event_action": "queued_synthetic_test",
                "occurred_at_ts": _TIMESTAMP - 30,
                "receiver_event_id": "events-inbox-browser-proof",
                "report_id": "hotpath-v1-synthetic-fail",
                "report_receipt_sha256": "d" * 64,
                "scenario": "safe-fail-event-path-proof",
                "success": False,
            },
            {
                "delivery_status": None,
                "event_action": "synthetic_only",
                "occurred_at_ts": _TIMESTAMP - 45,
                "receiver_event_id": None,
                "report_id": "hotpath-v1-synthetic-pass",
                "report_receipt_sha256": "e" * 64,
                "scenario": "safe-pass-ingestion-proof",
                "success": True,
            },
        ],
    }
    return json_object(raw)
