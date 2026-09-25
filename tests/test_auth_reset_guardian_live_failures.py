# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian ambiguous live results and auth-invalid containment."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from auth_reset_guardian.clients import (
    AccountScanError,
    BrokerProviderConfig,
    BrokerProviderSource,
    RemoteCallError,
)
from auth_reset_guardian.models import (
    AccountDescriptor,
    AccountObservation,
    ProviderCredentials,
    ResetCredit,
)
from domain_checks.testing import verify
from tests.auth_reset_guardian_support import (
    UTC,
    capture_http_call,
    credit_fixture,
    required_text,
)
from tests.auth_test_contract import FixtureContractError

BROKER_BEARER = "broker-admin-secret"
EXPECTED_RETRY_CALLS = 2
PROVIDER_BEARER = "fixture-oauth"

if TYPE_CHECKING:
    from auth_reset_guardian.clients import (
        JsonRequest,
    )
    from auth_reset_guardian.json_contract import JsonObject
    from tests.auth_reset_guardian_support import (
        HttpCall,
    )


def test_invalid_consume_result_is_ambiguous_and_reuses_exact_idempotency_key() -> None:
    """Retry an invalid consume result with the exact idempotency identity."""
    expiry = datetime(2026, 8, 11, 21, 8, 33, tzinfo=UTC)

    class InvalidResultHttp:
        """Return invalid provider results while capturing strict requests."""

        def __init__(self) -> None:
            """Initialize captured calls."""
            self.calls: list[HttpCall] = []

        def request(self, request_spec: JsonRequest) -> JsonObject:
            """Capture one consume request and return an invalid result.

            Returns:
                The resulting value.

            """
            self.calls.append(capture_http_call(request_spec))
            verify(request_spec.endpoint == "provider_consume_reset_credit")
            verify(request_spec.method == "POST")
            verify(request_spec.url.endswith("/consume"))
            verify(request_spec.headers["Authorization"] == f"Bearer {PROVIDER_BEARER}")
            verify(request_spec.payload is not None)
            verify(request_spec.ambiguous_on_failure is True)
            return {"code": "unsupported-provider-result", "windows_reset": 0}

        def payloads(self) -> list[JsonObject]:
            """Return every non-empty captured request payload."""
            payloads: list[JsonObject] = []
            for call in self.calls:
                payload = call["payload"]
                if payload is not None:
                    payloads.append(payload)
            return payloads

    http = InvalidResultHttp()
    source = BrokerProviderSource(
        BrokerProviderConfig(
            broker_url="http://broker.invalid",
            broker_admin_token=BROKER_BEARER,
            provider_base_url="https://provider.invalid/backend-api",
        ),
        http=http.request,
    )
    descriptor = AccountDescriptor(
        broker_account_id="broker-account-secret",
        label="info@pitchai.net",
        enabled=True,
    )
    credit = ResetCredit.from_provider(
        credit_fixture(credit_id="provider-credit-secret", expires_at=expiry),
    )
    observation = AccountObservation(
        descriptor=descriptor,
        captured_at=expiry - timedelta(hours=1),
        broker_state={"availability": "available"},
        usage_state={},
        available_count=1,
        credits=(credit,),
        credentials=ProviderCredentials(
            access_token=PROVIDER_BEARER,
            account_id="chatgpt-account-secret",
        ),
    )

    with pytest.raises(RemoteCallError) as captured:
        _ = source.consume_credit(observation, credit, "durable-key")
    verify(captured.value.ambiguous is True)
    verify(captured.value.error_code == "invalid_result_payload")
    verify(len(http.calls) == EXPECTED_RETRY_CALLS)
    request_ids: set[str] = set()
    credit_ids: set[str] = set()
    for payload in http.payloads():
        request_ids.add(required_text(payload, "redeem_request_id"))
        credit_ids.add(required_text(payload, "credit_id"))
    verify(request_ids == {"durable-key"})
    verify(credit_ids == {"provider-credit-secret"})


def test_live_source_stops_after_broker_reports_auth_invalid() -> None:
    """Stop before auth export when the broker marks an account invalid."""

    class FakeHttp:
        """Expose only the broker requests allowed before auth-invalid stop."""

        def __init__(self) -> None:
            """Initialize captured endpoints."""
            self.endpoints: list[str] = []

        def request(self, request_spec: JsonRequest) -> JsonObject:
            """Capture one broker request and return its bounded result.

            Returns:
                The resulting value.

            Raises:
                FixtureContractError: If an unexpected provider call occurs.

            """
            self.endpoints.append(request_spec.endpoint)
            verify(request_spec.method in {"GET", "POST"})
            verify(request_spec.url.startswith("http://broker.invalid/"))
            verify(request_spec.headers["Authorization"] == f"Bearer {BROKER_BEARER}")
            verify(request_spec.payload is None)
            verify(request_spec.ambiguous_on_failure is False)
            if request_spec.endpoint == "broker_list_accounts":
                return {
                    "accounts": [
                        {
                            "metadata": {
                                "account_id": "invalid-account",
                                "label": "sales@pitchai.net",
                                "enabled": True,
                            },
                        },
                    ],
                }
            if request_spec.endpoint == "broker_analytics_probe":
                return {
                    "metadata": {"label": "sales@pitchai.net"},
                    "state": {
                        "availability": "auth_invalid",
                        "analytics": {"errors": {}},
                    },
                }
            msg = "auth-invalid account must not be exported or called at provider"
            raise FixtureContractError(msg)

        def recorded_endpoints(self) -> list[str]:
            """Return a copy of captured endpoint names."""
            return list(self.endpoints)

    http = FakeHttp()
    source = BrokerProviderSource(
        BrokerProviderConfig(
            broker_url="http://broker.invalid",
            broker_admin_token=BROKER_BEARER,
        ),
        http=http.request,
    )
    descriptor = source.list_accounts()[0]
    with pytest.raises(AccountScanError) as captured:
        _ = source.refresh_account(descriptor)
    verify(captured.value.error_code == "broker_auth_invalid")
    verify(
        http.recorded_endpoints()
        == [
            "broker_list_accounts",
            "broker_analytics_probe",
        ],
    )
