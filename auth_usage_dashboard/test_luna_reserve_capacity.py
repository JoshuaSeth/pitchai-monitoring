# Copyright (c) 2026 PitchAI. All rights reserved.
"""Contract and protected-route proof for Luna reserve visibility."""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final

from ._scheduling_capacity_test_fixtures import (
    StaticCapacityService,
    dashboard_settings,
    operator_snapshot,
)
from ._timeseries_test_fixtures import UsageTimeSeriesCase, check, check_close, check_equal
from .luna_reserve_capacity import LUNA_RESERVE_SCHEMA_VERSION, build_luna_reserve_snapshot
from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import test_client_factory
from .timeseries_types import require_object

if TYPE_CHECKING:
    from .service import CapacityService, StateSource
    from .timeseries_types import JsonObject

_TOTAL_POINTS = 400.0
_REMAINING_POINTS = 400.0
_SAFE_DRAIN_POINTS = 240.0
_ACTIVE_ROUTABLE_POINTS = 80.0
_STRANDED_POINTS = 160.0
_PROTECTED_POINTS = 80.0


@final
class LunaReserveCapacityTest(UsageTimeSeriesCase):
    """Prove exact-meter projection, redaction, and route protection."""

    @staticmethod
    def test_projection_exposes_safe_headroom_without_account_identity() -> None:
        """Expose actionable reserve totals while retaining aggregate-only scope."""
        snapshot = build_luna_reserve_snapshot(_broker_capacity_snapshot())
        reserve = require_object(snapshot.get("luna_reserve"), description="Luna reserve")

        check_equal(snapshot.get("schema_version"), LUNA_RESERVE_SCHEMA_VERSION, "schema version")
        check_equal(reserve.get("model"), "gpt-reserve", "reserve model")
        check_equal(reserve.get("quality_tier"), "luna", "quality tier")
        check(reserve.get("reserve_only") is True, "reserve-only flag was lost")
        check_close(reserve.get("maximum_known_points"), _TOTAL_POINTS, "total points")
        check_close(reserve.get("remaining_points"), _REMAINING_POINTS, "remaining points")
        check_close(reserve.get("safe_drain_points"), _SAFE_DRAIN_POINTS, "safe-drain points")
        check_close(reserve.get("active_routable_points"), _ACTIVE_ROUTABLE_POINTS, "routable points")
        check_equal(reserve.get("health"), "active_routable", "reserve health")
        check_equal(reserve.get("reliability_status"), "provider_meter_observed", "reliability")
        encoded = json.dumps(snapshot)
        check("account_id" not in encoded, "account identifier escaped")
        check("account_label" not in encoded, "account label escaped")

    def test_endpoint_is_protected_and_returns_validated_reserve(self) -> None:
        """Require PitchAI identity before returning broker reserve capacity."""
        service = StaticCapacityService(operator_snapshot())
        application = create_scheduling_app(
            dashboard_settings(self.root),
            source=cast("StateSource", object()),
            service=cast("CapacityService", cast("object", service)),
            luna_capacity_reader=partial(
                build_luna_reserve_snapshot,
                _broker_capacity_snapshot(),
            ),
        )

        with test_client_factory(application) as client:
            denied = client.get("/api/v1/luna-reserve")
            response = client.get(
                "/api/v1/luna-reserve",
                headers={"X-PitchAI-Email": "priority-engine@pitchai.net"},
            )

            check_equal(denied.status_code, int(HTTPStatus.UNAUTHORIZED), "missing identity status")
            check_equal(response.status_code, int(HTTPStatus.OK), "Luna endpoint status")
            payload = require_object(response.json(), description="Luna endpoint response")
            reserve = require_object(payload.get("luna_reserve"), description="Luna reserve")
            check_close(reserve.get("active_routable_points"), _ACTIVE_ROUTABLE_POINTS, "endpoint points")
            check("private-one@pitchai.net" not in response.text, "operator identity escaped")

        check(service.started, "service did not start")
        check(service.stopped, "service did not stop")


def _broker_capacity_snapshot() -> JsonObject:
    """Return one identity-free auth-broker aggregate fixture."""
    return {
        "schema_version": 1,
        "observed_at": "2026-09-02T16:22:00Z",
        "luna_reserve": {
            "model": "gpt-reserve",
            "quality_tier": "luna",
            "metered_feature": "base_model_inference",
            "reserve_only": True,
            "safety_floor_percent": 20,
            "observed_accounts": 4,
            "healthy_standard_accounts": 3,
            "healthy_last_resort_accounts": 1,
            "active_routable_accounts": 1,
            "maximum_known_points": _TOTAL_POINTS,
            "remaining_points": _REMAINING_POINTS,
            "safe_drain_points": _SAFE_DRAIN_POINTS,
            "active_routable_points": _ACTIVE_ROUTABLE_POINTS,
            "stranded_safe_drain_points": _STRANDED_POINTS,
            "protected_last_resort_points": _PROTECTED_POINTS,
            "remaining_percent_min": 100,
            "remaining_percent_max": 100,
            "remaining_percent_average": 100,
            "next_reset_at": "2026-09-09T16:19:32Z",
            "latest_reset_at": "2026-09-09T16:21:33Z",
            "oldest_observed_at": "2026-09-02T16:19:32Z",
            "latest_observed_at": "2026-09-02T16:21:33Z",
            "health": "healthy",
        },
    }
