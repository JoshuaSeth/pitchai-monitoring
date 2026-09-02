# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deterministic central-directory fixtures for scheduler observer proofs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from .json_types import json_object
from .scheduler_cell_directory import scheduler_cell_directory

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject
    from .scheduler_cell_directory import SchedulerCellObservation

JEFF_BOOT_ONE = "db03389a-1778-43eb-907b-858d0dd21a42"
JEFF_BOOT_TWO = "692dd41b-5dcd-4879-9c39-8aeae0731636"
MAIN_BOOT = "a9b38448-e66b-4265-aa4b-88ee21370bbb"
_JEFF_ID = "750f0510-6449-54fa-acae-4965e7800b59"
_MAIN_ID = "2f2f06ca-0cde-5341-bc15-c66566207064"


def cell_observation(
    *,
    now: float,
    slug: str = "dev-jeff-cell-two",
    boot_id: str = JEFF_BOOT_ONE,
    last_received_at: float | None = None,
    pressure_updates: JsonObject | None = None,
) -> SchedulerCellObservation:
    """Return one healthy schema-four scheduling-cell observation."""
    pressure: JsonObject = {
        "scheduler_schema_version": 4,
        "general_agent_create_eligible": 1,
        "app_server_ready": 1,
        "new_lane_storage_ready": 1,
        "new_lane_storage_root": "/mnt/pitchai-dev-data",
        "master_service_host": 0,
        "root_disk_used_percent": 56.0,
        "root_disk_free_bytes": 849_000_000_000,
        "work_storage_used_percent": 56.0,
        "work_storage_free_bytes": 849_000_000_000,
        "work_storage_same_device_as_root": 1,
        "direct_unaccepted_observation_ready": 1,
        "direct_unaccepted_work_count": 0,
        "direct_unaccepted_requested_count": 0,
        "direct_unaccepted_dispatching_count": 0,
        "direct_unaccepted_oldest_age_seconds": 0.0,
    }
    pressure.update(pressure_updates or {})
    received_at = now if last_received_at is None else last_received_at
    payload = json_object(
        cast(
            "JsonInput",
            {
                "cells": [
                    {
                        "cell_id": _MAIN_ID if slug == "dev-main-cell-one" else _JEFF_ID,
                        "slug": slug,
                        "boot_id": boot_id,
                        "registry_status": "active",
                        "status": "online",
                        "health": "healthy",
                        "placement_eligible": True,
                        "last_received_at": _timestamp(received_at),
                        "projection_sequence": 1,
                        "projection_received_at": _timestamp(received_at),
                        "services": [
                            {
                                "workload_key": "agent_runtime",
                                "reported_health": "healthy",
                                "placement_eligible": True,
                            },
                        ],
                        "routes": [
                            {
                                "workload_key": "agent_runtime",
                                "compatibility_mode": "cell_v2",
                                "status": "active",
                            },
                        ],
                        "pressure": pressure,
                    },
                ],
            },
        ),
    )
    return scheduler_cell_directory(payload)[0]


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
