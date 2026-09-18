# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compatibility coverage for combined native and scheduling API service."""

from __future__ import annotations

import unittest
from pathlib import Path

from ._mobile_test_crypto import AttestationCryptoFixture
from ._mobile_test_fixtures import (
    FakeSource,
    as_state_source,
    dashboard_settings,
    mobile_settings,
)
from ._mobile_test_runtime import TEST_CLIENT_FACTORY
from ._timeseries_test_fixtures import check, check_equal, isolated_root
from .mobile_app import create_app
from .scheduling_capacity_check import validate_scheduling_capacity_payload
from .timeseries_types import require_object


class MobileSchedulingCompatibilityCase(unittest.TestCase):
    """Prove the production process preserves both protected API families."""

    def test_native_composition_preserves_scheduling_capacity_route(self) -> None:
        """Keep the queue-drainer contract when native routes are enabled."""
        root = self.enterContext(isolated_root())
        crypto = AttestationCryptoFixture(root)
        source = FakeSource()
        application = create_app(
            dashboard_settings(root),
            source=as_state_source(source),
            mobile_settings=mobile_settings(root, crypto.root_path),
        )
        with TEST_CLIENT_FACTORY(application) as client:
            denied = client.get("/api/v1/scheduling-capacity")
            response = client.get(
                "/api/v1/scheduling-capacity",
                headers={"X-PitchAI-Email": "priority-engine@pitchai.net"},
            )
        check_equal(denied.status_code, 401, "scheduler route identity status")
        check_equal(response.status_code, 200, "scheduler route status")
        payload = require_object(
            response.json(),
            description="composed scheduling response",
        )
        validate_scheduling_capacity_payload(payload)

    @staticmethod
    def test_production_image_runs_the_composed_server() -> None:
        """Keep production on the entrypoint that installs both API families."""
        dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile.auth-usage"
        source = dockerfile.read_text(encoding="utf-8")
        check(
            'CMD ["python", "-m", "auth_usage_dashboard.server"]' in source,
            "production image bypasses the composed server",
        )
