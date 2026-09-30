# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained worker state documents used by the monitoring health proof."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .json_types import json_object

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .json_types import JsonObject


def monitor_document(
    *,
    observed_at: float,
    write_fail_streak: int = 0,
    browser_degraded: bool = False,
) -> JsonObject:
    """Return one retained monitor cycle document at the requested age."""
    return json_object(
        {
            "version": 6,
            "updated_at": datetime.fromtimestamp(observed_at, tz=UTC).isoformat(),
            "meta": {"state_write_fail_streak": write_fail_streak},
            "browser_degraded_active": browser_degraded,
        },
    )


def runner_document(
    *,
    observed_at: float,
    phase: str = "idle",
    active_started: float | None = None,
    claim_failures: int = 0,
) -> JsonObject:
    """Return one retained runner heartbeat document at the requested age."""
    return json_object(
        {
            "version": 1,
            "phase": phase,
            "updated_at_ts": observed_at,
            "started_at_ts": observed_at,
            "consecutive_claim_failures": claim_failures,
            "active_job_test_id": "smoke.case" if phase == "running" else None,
            "active_job_started_ts": active_started,
        },
    )


def dependency_document(*, observed_at: float) -> JsonObject:
    """Return one retained database dependency collector snapshot."""
    return json_object(
        {
            "version": 2,
            "status": "ok",
            "generated_at_ts": observed_at,
            "collector": {
                "status": "healthy",
                "observed_at_ts": observed_at,
                "last_successful_cycle_at_ts": observed_at,
            },
            "dependencies": [{"status": "up"}],
        },
    )


def observer_document(*, observed_at: float) -> JsonObject:
    """Return one retained scheduler placement observer checkpoint."""
    return json_object(
        {
            "version": 1,
            "bootstrapped": True,
            "updated_at_ts": observed_at,
            "last_successful_poll_at_ts": observed_at,
            "last_error": None,
        },
    )


def producer_document(*, observed_at: float) -> JsonObject:
    """Return one retained domain incident producer checkpoint."""
    return json_object(
        {
            "version": 1,
            "producer": {
                "status": "healthy",
                "bootstrapped": True,
                "updated_at_ts": observed_at,
                "pending_count": 0,
                "open_incident_count": 0,
                "last_error": None,
            },
        },
    )


def role_documents(*, now: float, ages: Mapping[str, float]) -> dict[str, JsonObject]:
    """Return one retained worker document per role at the requested ages."""
    return {
        "monitor": monitor_document(observed_at=now - ages["monitor"]),
        "runner": runner_document(observed_at=now - ages["runner"]),
        "database-dependency": dependency_document(observed_at=now - ages["database-dependency"]),
        "scheduler-observer": observer_document(observed_at=now - ages["scheduler-observer"]),
        "domain-incident": producer_document(observed_at=now - ages["domain-incident"]),
    }
