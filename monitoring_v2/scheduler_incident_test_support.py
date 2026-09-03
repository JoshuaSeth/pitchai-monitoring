# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared scheduler-incident fixtures for receiver-boundary tests."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast

from .json_types import json_object

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject

EVENT_ID = 111
RECOVERY_EVENT_ID = 112
TOKEN = hashlib.sha256(b"scheduler-observer-test-token").hexdigest()
_CORRELATION_ID = "22222222-2222-4222-8222-222222222222"
_RECOVERY_CORRELATION_ID = "33333333-3333-4333-8333-333333333333"
_COMMAND_ID = "44444444-4444-4444-8444-444444444444"


def incident_feed() -> JsonObject:
    """Return one storage-aware terminal placement incident page."""
    occurred_at = "2026-09-02T16:00:00.500000Z"
    return json_object(
        cast(
            "JsonInput",
            {
                "transitions": [_placement_failure(occurred_at)],
                "next_occurred_at": occurred_at,
                "next_event_id": EVENT_ID,
            },
        ),
    )


def recovery_feed() -> JsonObject:
    """Return one completed-create recovery linked to the fixture failure."""
    failure_at = "2026-09-02T16:00:00.500000Z"
    recovered_at = "2026-09-02T16:05:00.500000Z"
    return json_object(
        cast(
            "JsonInput",
            {
                "transitions": [
                    {
                        "audit_event_id": RECOVERY_EVENT_ID,
                        "occurred_at": recovered_at,
                        "correlation_id": _RECOVERY_CORRELATION_ID,
                        "signal_schema_version": 1,
                        "kind": "new_lane_placement_recovered",
                        "project_key": "quickchat",
                        "origin_branch": "origin/staging",
                        "assigned_cell_slug": "dev-jeff-cell-two",
                        "command_id": _COMMAND_ID,
                        "new_lane_storage_root": "/mnt/pitchai-dev-data",
                        "prior_failure": _placement_failure(failure_at),
                    },
                ],
                "next_occurred_at": recovered_at,
                "next_event_id": RECOVERY_EVENT_ID,
            },
        ),
    )


def _placement_failure(occurred_at: str) -> JsonObject:
    return json_object(
        cast(
            "JsonInput",
            {
                "audit_event_id": EVENT_ID,
                "occurred_at": occurred_at,
                "correlation_id": _CORRELATION_ID,
                "signal_schema_version": 2,
                "kind": "new_lane_placement_failed",
                "local_agent_id": "quickchat-safe-canary-20260902",
                "project_key": "quickchat",
                "origin_branch": "origin/staging",
                "rejection_summary": "No cell can safely create this new lane.",
                "cells": [
                    {
                        "slug": "dev-jeff-cell-two",
                        "reasons": [
                            "project is not materialized locally",
                            "target project fetch proof is absent",
                        ],
                        "storage_roots": [
                            {
                                "path": "/",
                                "role": "root",
                                "selected_for_new_lanes": False,
                                "used_percent": 16.0,
                                "free_bytes": 901943132160,
                                "same_device_as_root": True,
                                "reasons": [],
                            },
                            {
                                "path": "/root/code",
                                "role": "new_lane",
                                "selected_for_new_lanes": True,
                                "used_percent": 16.0,
                                "free_bytes": 901943132160,
                                "same_device_as_root": True,
                                "reasons": [],
                            },
                        ],
                    },
                    {
                        "slug": "dev-main-cell-one",
                        "reasons": [
                            "heartbeat is stale",
                            "critical capacity signal: root disk 100.0% used with 0.0 GiB free",
                        ],
                        "storage_roots": [
                            {
                                "path": "/",
                                "role": "root",
                                "selected_for_new_lanes": False,
                                "used_percent": 100.0,
                                "free_bytes": 0,
                                "same_device_as_root": True,
                                "reasons": ["critical capacity: 100.0% used with 0.0 GiB free"],
                            },
                            {
                                "path": "/mnt/pitchai-dev-data",
                                "role": "new_lane",
                                "selected_for_new_lanes": True,
                                "used_percent": 75.0,
                                "free_bytes": 233592733696,
                                "same_device_as_root": False,
                                "reasons": [],
                            },
                        ],
                    },
                ],
            },
        ),
    )
