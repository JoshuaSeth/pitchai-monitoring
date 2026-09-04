# Copyright (c) 2026 PitchAI. All rights reserved.
"""Endpoint and deployment-path proof for scheduling capacity."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

from ._scheduling_capacity_test_fixtures import (
    StaticCapacityService,
    dashboard_settings,
    operator_snapshot,
)
from ._timeseries_test_fixtures import UsageTimeSeriesCase, check, check_equal
from .scheduling_app import create_scheduling_app
from .scheduling_capacity_check import validate_scheduling_capacity_payload
from .scheduling_web_runtime import test_client_factory
from .timeseries_types import require_object

if TYPE_CHECKING:
    from .service import CapacityService, StateSource


@final
class SchedulingCapacityEndpointTest(UsageTimeSeriesCase):
    """Prove the aggregate endpoint and artifact validation boundary."""

    def test_endpoint_is_protected_and_identity_free(self) -> None:
        """Require PitchAI identity and return only the validated aggregate shape."""
        service = StaticCapacityService(operator_snapshot())
        application = create_scheduling_app(
            dashboard_settings(self.root),
            source=cast("StateSource", object()),
            service=cast("CapacityService", cast("object", service)),
        )

        with test_client_factory(application) as client:
            denied = client.get("/api/v1/scheduling-capacity")
            foreign = client.get(
                "/api/v1/scheduling-capacity",
                headers={"X-PitchAI-Email": "operator@example.com"},
            )
            response = client.get(
                "/api/v1/scheduling-capacity",
                headers={"X-PitchAI-Email": "priority-engine@pitchai.net"},
            )

            check_equal(
                denied.status_code,
                int(HTTPStatus.UNAUTHORIZED),
                "missing identity status",
            )
            check_equal(
                foreign.status_code,
                int(HTTPStatus.UNAUTHORIZED),
                "foreign identity status",
            )
            check_equal(
                response.status_code,
                int(HTTPStatus.OK),
                "scheduler endpoint status",
            )
            decoded = response.json()
            payload = require_object(decoded, description="scheduling response")
            validate_scheduling_capacity_payload(payload)
            check(
                "private-one@pitchai.net" not in response.text,
                "first identity escaped endpoint",
            )
            check(
                "private-two@pitchai.net" not in response.text,
                "second identity escaped endpoint",
            )

        check(service.started, "service did not start")
        check(service.stopped, "service did not stop")

    @staticmethod
    def test_deployer_validates_with_the_candidate_python_runtime() -> None:
        """Keep host Python compatibility out of the artifact validation path."""
        script_path = (
            Path(__file__).resolve().parents[1]
            / "ops"
            / "deploy_codex_usage_dashboard.sh"
        )
        script = script_path.read_text(encoding="utf-8")

        check(
            'docker exec --interactive "${name}" python -m' in script,
            "deployer does not validate with the exact candidate container",
        )
        check(
            'check_dashboard "${CANARY_PORT}" "${canary}"' in script,
            "canary name is not bound to the deployment check",
        )
        check(
            'check_dashboard "${PROD_PORT}" "${CONTAINER}"' in script,
            "production name is not bound to the deployment check",
        )
        check(
            'PYTHONPATH="${REPO_ROOT}" python3 -m' not in script,
            "deployer still imports target code with the host Python runtime",
        )
