# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP integration coverage for the protected native capacity contract."""

from __future__ import annotations

import base64
import json
import unittest
from typing import TYPE_CHECKING

from ._mobile_test_crypto import AttestationCryptoFixture
from ._mobile_test_fixtures import (
    FakeSource,
    as_state_source,
    dashboard_settings,
    mobile_settings,
    require_integer,
    require_text,
)
from ._mobile_test_runtime import TEST_CLIENT_FACTORY
from ._timeseries_test_fixtures import check, check_equal, isolated_root, require_array
from .mobile_app import create_app
from .mobile_challenges import Challenge, canonical_client_data
from .timeseries_types import require_object

if TYPE_CHECKING:
    from pathlib import Path

    from ._mobile_test_runtime import TestClientSurface
    from .mobile_challenges import ChallengePurpose
    from .timeseries_types import JsonObject

_FORBIDDEN_RESPONSE_TEXT = (
    "private-account@example.com",
    "must-never-escape",
    "auth_json",
    "access_token",
    "refresh_token",
    "admin_token",
    "receipt",
    "public_key",
)


class MobileRouteCase(unittest.TestCase):
    """Exercise native routes through the real application lifespan."""

    root: Path
    crypto: AttestationCryptoFixture

    def setUp(self) -> None:
        """Create one isolated application and certificate root."""
        self.root = self.enterContext(isolated_root())
        self.crypto = AttestationCryptoFixture(self.root)

    def test_enroll_assert_and_return_only_native_contract(self) -> None:
        """Enroll, authenticate, and return secret-free live capacity."""
        source = FakeSource()
        application = create_app(
            dashboard_settings(self.root),
            source=as_state_source(source),
            mobile_settings=mobile_settings(self.root, self.crypto.root_path),
        )
        with TEST_CLIENT_FACTORY(application) as client:
            attestation_challenge = self._challenge(client, purpose="attest")
            challenge_bytes = base64.b64decode(
                require_text(
                    attestation_challenge.get("challenge"),
                    "attestation challenge",
                ),
                validate=True,
            )
            attested = client.post(
                "/api/v1/mobile/attest",
                json={
                    "challenge_id": require_text(
                        attestation_challenge.get("challenge_id"),
                        "attestation challenge id",
                    ),
                    "key_id": self.crypto.key_id,
                    "attestation": self.crypto.attestation(challenge_bytes),
                },
            )
            check_equal(attested.status_code, 200, "attestation response status")
            attested_payload = require_object(
                attested.json(),
                description="attestation response",
            )
            check(attested_payload.get("registered") is True, "registration result")
            capacity_challenge = self._challenge(client, purpose="capacity")
            challenge = self._decoded_challenge(capacity_challenge)
            response = client.post(
                "/api/v1/mobile/capacity",
                json={
                    "challenge_id": challenge.identifier,
                    "key_id": self.crypto.key_id,
                    "assertion": self.crypto.assertion(
                        canonical_client_data(challenge),
                        counter=1,
                    ),
                },
            )
        check(source.closed, "application lifespan closes the state source")
        check_equal(response.status_code, 200, "capacity response status")
        payload = require_object(response.json(), description="capacity response")
        self._check_capacity_payload(payload)

    def test_enrollment_route_is_closed_when_configured_closed(self) -> None:
        """Expose the safe closed-enrollment failure without adding a key."""
        source = FakeSource()
        application = create_app(
            dashboard_settings(self.root),
            source=as_state_source(source),
            mobile_settings=mobile_settings(
                self.root,
                self.crypto.root_path,
                enrollment_enabled=False,
            ),
        )
        with TEST_CLIENT_FACTORY(application) as client:
            response = client.post(
                "/api/v1/mobile/challenge",
                json={"purpose": "attest", "key_id": self.crypto.key_id},
            )
        check_equal(response.status_code, 403, "closed-enrollment response status")
        payload = require_object(
            response.json(),
            description="closed-enrollment response",
        )
        detail = require_object(
            payload.get("detail"),
            description="closed-enrollment detail",
        )
        check_equal(detail.get("code"), "enrollment_closed", "closed-enrollment code")

    def test_mobile_routes_are_absent_when_disabled(self) -> None:
        """Avoid exposing native endpoints until mobile mode is enabled."""
        source = FakeSource()
        application = create_app(
            dashboard_settings(self.root),
            source=as_state_source(source),
            mobile_settings=mobile_settings(
                self.root,
                self.crypto.root_path,
                enabled=False,
            ),
        )
        with TEST_CLIENT_FACTORY(application) as client:
            response = client.post(
                "/api/v1/mobile/challenge",
                json={"purpose": "capacity", "key_id": self.crypto.key_id},
            )
        check_equal(response.status_code, 404, "disabled native route status")

    def _challenge(
        self,
        client: TestClientSurface,
        *,
        purpose: ChallengePurpose,
    ) -> JsonObject:
        response = client.post(
            "/api/v1/mobile/challenge",
            json={"purpose": purpose, "key_id": self.crypto.key_id},
        )
        check_equal(response.status_code, 200, f"{purpose} challenge status")
        return require_object(
            response.json(),
            description=f"{purpose} challenge response",
        )

    def _decoded_challenge(self, payload: JsonObject) -> Challenge:
        return Challenge(
            identifier=require_text(
                payload.get("challenge_id"),
                "capacity challenge id",
            ),
            value=base64.b64decode(
                require_text(payload.get("challenge"), "capacity challenge"),
                validate=True,
            ),
            purpose="capacity",
            key_id=self.crypto.key_id,
            created_monotonic=0,
        )

    @staticmethod
    def _check_capacity_payload(payload: JsonObject) -> None:
        check_equal(
            require_integer(payload.get("schema_version"), "schema version"),
            1,
            "schema version",
        )
        summary = require_object(payload.get("summary"), description="capacity summary")
        check_equal(summary.get("usable_now"), 1, "usable account count")
        aggregates = require_object(
            summary.get("window_aggregates"),
            description="window aggregates",
        )
        five_hour = require_object(
            aggregates.get("five_hour"),
            description="five-hour aggregate",
        )
        check_equal(
            five_hour.get("remaining_points"),
            80.0,
            "five-hour remaining points",
        )
        accounts = require_array(payload.get("accounts"), "mobile accounts")
        account = require_object(accounts[0], description="first mobile account")
        check_equal(account.get("label"), "seth-primary", "account label")
        account_window = require_object(
            account.get("five_hour"),
            description="account five-hour window",
        )
        check_equal(
            account_window.get("remaining_percent"),
            80.0,
            "account remaining percent",
        )
        refresh = require_object(
            payload.get("refresh_policy"),
            description="refresh policy",
        )
        check_equal(
            refresh.get("recommended_background_interval_seconds"),
            900,
            "refresh interval",
        )
        encoded = json.dumps(payload)
        for forbidden in _FORBIDDEN_RESPONSE_TEXT:
            check(forbidden not in encoded, f"capacity response excludes {forbidden}")
