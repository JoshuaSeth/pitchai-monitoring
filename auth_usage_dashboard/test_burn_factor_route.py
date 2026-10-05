# Copyright (c) 2026 PitchAI. All rights reserved.
"""Endpoint proof for the protected burn-factor route."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from ._scheduling_capacity_test_fixtures import StaticCapacityService, dashboard_settings, operator_snapshot
from ._timeseries_test_fixtures import check, check_equal
from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import test_client_factory
from .timeseries_types import require_object

if TYPE_CHECKING:
    from pathlib import Path

    from .service import CapacityService, StateSource

OPERATOR = {"X-PitchAI-Email": "priority-engine@pitchai.net"}
DEFAULT_VIEWS = 2


def test_burn_factor_route_requires_identity_validates_pairs_and_defaults_to_two_views(tmp_path: Path) -> None:
    """Prove the route is SSO-protected, rejects bad pairs and serves the two default views."""
    application = create_scheduling_app(
        dashboard_settings(tmp_path),
        service=cast("CapacityService", cast("object", StaticCapacityService(operator_snapshot()))),
        source=cast("StateSource", object()),
    )
    with test_client_factory(application) as client:
        check_equal(client.get("/api/v1/burn-factor").status_code, int(HTTPStatus.UNAUTHORIZED), "identity required")
        bad = client.get("/api/v1/burn-factor?pairs=1m:24h", headers=OPERATOR)
        check_equal(bad.status_code, int(HTTPStatus.BAD_REQUEST), "an out-of-range window is a client error")
        response = client.get("/api/v1/burn-factor", headers=OPERATOR)
        check_equal(response.status_code, int(HTTPStatus.OK), "default request succeeds")
        payload = require_object(response.json(), description="burn factor payload")
        results = payload.get("results")
        check(isinstance(results, list) and len(results) == DEFAULT_VIEWS, "30m:24h and 24h:6d are the defaults")
        custom = require_object(
            client.get("/api/v1/burn-factor?pairs=2h:3d", headers=OPERATOR).json(),
            description="custom",
        )
        custom_results = custom.get("results")
        first = require_object(custom_results[0] if isinstance(custom_results, list) else None, description="first")
        check_equal((first.get("rolling"), first.get("horizon")), ("2h", "3d"), "any custom pair is answered")
