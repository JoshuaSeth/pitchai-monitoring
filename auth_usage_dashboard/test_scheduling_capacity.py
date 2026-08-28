# Copyright (c) 2026 PitchAI. All rights reserved.
"""Aggregate projection, protection, and deployment-contract proof."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final

from fastapi.testclient import TestClient

from ._scheduling_capacity_test_fixtures import (
    StaticCapacityService,
    dashboard_settings,
    operator_snapshot,
)
from ._timeseries_test_fixtures import (
    UsageTimeSeriesCase,
    check,
    check_close,
    check_equal,
    require_array,
)
from .scheduling_app import create_scheduling_app
from .scheduling_capacity import (
    SCHEDULING_CAPACITY_SCHEMA_VERSION,
    build_scheduling_capacity_snapshot,
)
from .scheduling_capacity_check import validate_scheduling_capacity_payload
from .timeseries_types import optional_object, require_object

if TYPE_CHECKING:
    from ._scheduling_capacity_test_fixtures import HttpClientContract
    from .service import CapacityService, StateSource
    from .timeseries_types import JsonObject

_SOURCE_FRESHNESS_SECONDS = 30
_FIVE_HOUR_REMAINING_POINTS = 75.5
_BURN_POINTS_PER_HOUR = 12.5
_WEEKLY_REMAINING_POINTS = 80.0


@final
class SchedulingCapacityTest(UsageTimeSeriesCase):
    """Prove the scheduler contract is deterministic, protected, and redacted."""

    @staticmethod
    def test_projection_is_aggregate_only_and_deterministic() -> None:
        """Remove account identity while retaining scheduling evidence."""
        snapshot = operator_snapshot()
        first = build_scheduling_capacity_snapshot(snapshot)
        second = build_scheduling_capacity_snapshot(snapshot)

        source = _nested(first, "source")
        capacity = _nested(first, "capacity")
        burn = _nested(first, "burn")
        token_burn = _nested(first, "token_burn")
        check_equal(first, second, "deterministic projection")
        check_equal(first.get("schema_version"), SCHEDULING_CAPACITY_SCHEMA_VERSION, "schema version")
        check_equal(first.get("status"), "available", "projection status")
        check_equal(source.get("freshness_seconds"), _SOURCE_FRESHNESS_SECONDS, "source freshness")
        check_close(capacity.get("remaining_points"), _FIVE_HOUR_REMAINING_POINTS, "remaining points")
        check_equal(capacity.get("timeline_status"), "complete", "timeline status")
        check_close(burn.get("capacity_points_per_hour"), _BURN_POINTS_PER_HOUR, "burn rate")
        check(token_burn.get("diagnostic_only") is True, "token burn was treated as capacity")
        _check_five_hour_timeline(first)

        encoded = json.dumps(first)
        check("private-one" not in encoded, "first identity escaped")
        check("private-two" not in encoded, "second identity escaped")
        check("driver_with_identity" not in encoded, "runout driver escaped")
        validate_scheduling_capacity_payload(first)

    @staticmethod
    def test_projection_fails_closed_without_measurement() -> None:
        """Withhold capacity when the selected basis is unavailable."""
        snapshot = operator_snapshot()
        summary = _nested(snapshot, "summary")
        summary["capacity_basis"] = {
            "key": None,
            "label": None,
            "measurement_status": "unavailable",
        }

        projection = build_scheduling_capacity_snapshot(snapshot)
        capacity = _nested(projection, "capacity")
        check_equal(projection.get("status"), "unavailable", "missing measurement status")
        check(capacity.get("remaining_points") is None, "missing measurement exposed points")
        check(capacity.get("basis_key") is None, "missing measurement exposed a basis")

    @staticmethod
    def test_projection_excludes_unselectable_points() -> None:
        """Exclude remaining capacity from accounts unavailable for work."""
        snapshot = operator_snapshot()
        _nested(snapshot, "summary")["usable_now"] = 0
        accounts = require_array(snapshot.get("accounts"), "accounts")
        first_account = require_object(accounts[0], description="first account")
        first_account["selectable_now"] = False
        first_account["status"] = "five_hour_limited"

        projection = build_scheduling_capacity_snapshot(snapshot)
        capacity = _nested(projection, "capacity")
        check_equal(capacity.get("usable_accounts_now"), 0, "usable accounts")
        check_close(capacity.get("remaining_points"), 0.0, "selectable points")

    @staticmethod
    def test_projection_uses_only_selected_weekly_basis() -> None:
        """Keep weekly timeline math isolated from five-hour measurements."""
        snapshot = operator_snapshot()
        summary = _nested(snapshot, "summary")
        summary["capacity_basis"] = {
            "key": "weekly",
            "label": "Weekly",
            "reporting_accounts": 2,
            "eligible_accounts": 2,
            "measurement_status": "complete",
        }
        summary["window_aggregates"] = {
            "weekly": {
                "remaining_points": 150.0,
                "maximum_known_points": 200.0,
                "remaining_percent": 75.0,
            },
        }

        projection = build_scheduling_capacity_snapshot(snapshot)
        capacity = _nested(projection, "capacity")
        check_equal(capacity.get("basis_key"), "weekly", "capacity basis")
        check_close(capacity.get("remaining_points"), _WEEKLY_REMAINING_POINTS, "weekly points")
        automatic_resets = require_array(projection.get("automatic_resets"), "automatic resets")
        for event in automatic_resets:
            check_equal(optional_object(event).get("kind"), "weekly_reset", "weekly reset kind")

    @staticmethod
    def test_stale_inputs_are_degraded() -> None:
        """Expose staleness instead of silently treating capacity as fresh."""
        snapshot = operator_snapshot()
        _nested(snapshot, "source")["stale"] = True

        projection = build_scheduling_capacity_snapshot(snapshot)
        check_equal(projection.get("status"), "degraded", "stale status")
        check(_nested(projection, "source").get("stale") is True, "stale flag was lost")

    def test_endpoint_is_protected_and_identity_free(self) -> None:
        """Require PitchAI identity and return only the validated aggregate shape."""
        service = StaticCapacityService(operator_snapshot())
        application = create_scheduling_app(
            dashboard_settings(self.root),
            source=cast("StateSource", object()),
            service=cast("CapacityService", cast("object", service)),
        )

        with TestClient(application) as raw_client:
            client = cast("HttpClientContract", cast("object", raw_client))
            denied = client.get("/api/v1/scheduling-capacity")
            foreign = client.get(
                "/api/v1/scheduling-capacity",
                headers={"X-PitchAI-Email": "operator@example.com"},
            )
            response = client.get(
                "/api/v1/scheduling-capacity",
                headers={"X-PitchAI-Email": "priority-engine@pitchai.net"},
            )

            check_equal(denied.status_code, int(HTTPStatus.UNAUTHORIZED), "missing identity status")
            check_equal(foreign.status_code, int(HTTPStatus.UNAUTHORIZED), "foreign identity status")
            check_equal(response.status_code, int(HTTPStatus.OK), "scheduler endpoint status")
            decoded = response.json()
            payload = require_object(decoded, description="scheduling response")
            validate_scheduling_capacity_payload(payload)
            check("private-one@pitchai.net" not in response.text, "first identity escaped endpoint")
            check("private-two@pitchai.net" not in response.text, "second identity escaped endpoint")

        check(service.started, "service did not start")
        check(service.stopped, "service did not stop")


def _nested(payload: JsonObject, key: str) -> JsonObject:
    """Require one nested object in a scheduler payload.

    Returns:
        The narrowed JSON object.
    """
    return require_object(payload.get(key), description=key)


def _check_five_hour_timeline(payload: JsonObject) -> None:
    """Verify the first five-hour expiry and automatic reset sequence."""
    expiry_buckets = require_array(payload.get("expiry_buckets"), "expiry buckets")
    check_equal(len(expiry_buckets), 1, "expiry bucket count")
    expiry = require_object(expiry_buckets[0], description="expiry bucket")
    check_equal(expiry.get("kind"), "five_hour_window", "expiry kind")
    check_close(expiry.get("remaining_points"), _FIVE_HOUR_REMAINING_POINTS, "expiry points")

    automatic_resets = require_array(payload.get("automatic_resets"), "automatic resets")
    first_reset = require_object(automatic_resets[0], description="automatic reset")
    check_equal(first_reset.get("kind"), "five_hour_reset", "reset kind")
    check_equal(first_reset.get("restores_selectability_count"), 1, "restoring reset count")
    check_close(first_reset.get("capacity_points"), 200.0, "reset capacity")
    for event in automatic_resets:
        check_equal(optional_object(event).get("kind"), "five_hour_reset", "reset kind")
