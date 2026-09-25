# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian manual redemption and live-source credential behavior."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.clients import (
    BrokerProviderConfig,
    BrokerProviderSource,
    SimulationSource,
)
from auth_reset_guardian.guardian import Guardian
from domain_checks.testing import verify
from tests.auth_reset_guardian_support import (
    UTC,
    capture_http_call,
    credit_fixture,
    guardian_fixture,
)
from tests.auth_test_contract import required_value

BROKER_BEARER = "broker-admin-secret"
EXPECTED_MANUAL_REFRESH_COUNT = 3

if TYPE_CHECKING:
    from pathlib import Path

    from auth_reset_guardian.clients import (
        JsonRequest,
    )
    from auth_reset_guardian.json_contract import JsonObject
    from tests.auth_reset_guardian_support import (
        HttpCall,
    )


def test_manual_redemption_requires_exact_expiry_and_uses_two_reads(
    tmp_path: Path,
) -> None:
    """Require an exact expiry and two reads for manual redemption."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    expiry = now + timedelta(hours=12)
    source = SimulationSource(
        guardian_fixture(expires_at=expiry, credit_id="manual-credit", outcome="reset"),
        clock=lambda: now,
    )
    with AuditStore(tmp_path / "audit.sqlite3") as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).manual_redeem(
            account_label="info@pitchai.net",
            expires_at=expiry,
            reason="operator-confirmed-test",
            dry_run=False,
        )
    verify(summary.redemption_count == 1)
    verify(len(source.consume_calls) == 1)
    verify(next(iter(source.refresh_calls.values())) == EXPECTED_MANUAL_REFRESH_COUNT)


def test_simulation_fixture_round_trip_is_valid_json(tmp_path: Path) -> None:
    """Load a serialized simulation fixture through its public path boundary."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    fixture_path = tmp_path / "fixture.json"
    _ = fixture_path.write_text(
        json.dumps(guardian_fixture(expires_at=now + timedelta(hours=1))),
        encoding="utf-8",
    )
    source = SimulationSource.from_path(fixture_path, clock=lambda: now)
    verify(source.list_accounts()[0].label == "info@pitchai.net")


def test_live_source_uses_only_broker_oauth_and_targets_exact_credit() -> None:
    """Use only broker OAuth when consuming the exact provider credit."""
    expiry = datetime(2026, 8, 11, 21, 8, 33, tzinfo=UTC)

    class FakeHttp:
        """Return one complete live-source HTTP exchange."""

        def __init__(self) -> None:
            """Initialize captured requests."""
            self.calls: list[HttpCall] = []

        def request(self, request_spec: JsonRequest) -> JsonObject:
            """Capture one request and return its deterministic response.

            Returns:
                The resulting value.

            Raises:
                AssertionError: If the value violates the validation contract.

            """
            self.calls.append(capture_http_call(request_spec))
            if request_spec.endpoint == "broker_list_accounts":
                return {
                    "accounts": [
                        {
                            "metadata": {
                                "account_id": "broker-account-secret",
                                "label": "info@pitchai.net",
                                "enabled": True,
                                "priority": 10,
                            },
                        },
                    ],
                }
            if request_spec.endpoint == "broker_analytics_probe":
                return {
                    "metadata": {"label": "info@pitchai.net"},
                    "state": {
                        "availability": "available",
                        "last_probe_at": "2026-08-10T19:00:00Z",
                        "analytics": {"errors": {}},
                    },
                }
            if request_spec.endpoint == "broker_export_auth":
                return {
                    "OPENAI_API_KEY": "must-never-be-used",
                    "tokens": {
                        "access_token": "fixture-oauth",
                        "refresh_token": "fixture-refresh",
                        "account_id": "chatgpt-account-secret",
                    },
                }
            if request_spec.endpoint == "provider_usage":
                return {
                    "rate_limit": {
                        "allowed": False,
                        "limit_reached": True,
                        "primary_window": {"used_percent": 100},
                        "secondary_window": None,
                    },
                    "rate_limit_reset_credits": {
                        "available_count": 1,
                        "applicable_available_count": 1,
                    },
                }
            if request_spec.endpoint == "provider_reset_credits":
                return {
                    "available_count": 1,
                    "credits": [
                        credit_fixture(
                            credit_id="provider-credit-secret",
                            expires_at=expiry,
                        ),
                    ],
                }
            if request_spec.endpoint == "provider_consume_reset_credit":
                payload = required_value(
                    request_spec.payload,
                    label="provider consume payload",
                )
                verify(payload["credit_id"] == "provider-credit-secret")
                verify(payload["redeem_request_id"] == "durable-key")
                return {"code": "reset", "windows_reset": 2}
            raise AssertionError(request_spec.endpoint)

        def provider_calls(self) -> list[HttpCall]:
            """Return only captured calls made to provider endpoints."""
            calls: list[HttpCall] = [call for call in self.calls if call["endpoint"].startswith("provider_")]
            return calls

    http = FakeHttp()
    source = BrokerProviderSource(
        BrokerProviderConfig(
            broker_url="http://broker.invalid",
            broker_admin_token=BROKER_BEARER,
            provider_base_url="https://provider.invalid/backend-api",
        ),
        http=http.request,
    )
    descriptor = source.list_accounts()[0]
    observation = source.refresh_account(descriptor)
    result = source.consume_credit(observation, observation.credits[0], "durable-key")
    verify(result.code == "reset")
    provider_calls = http.provider_calls()
    verify(provider_calls)
    for call in provider_calls:
        verify(call["headers"]["Authorization"] == "Bearer fixture-oauth")
        verify(call["headers"]["ChatGPT-Account-Id"] == "chatgpt-account-secret")
        serialized = json.dumps(call)
        verify("must-never-be-used" not in serialized)
        verify("fixture-refresh" not in serialized)
