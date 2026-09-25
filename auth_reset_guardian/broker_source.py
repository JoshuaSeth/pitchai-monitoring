# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read broker-managed OAuth state and call provider reset endpoints."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from .broker_credentials import (
    BrokerCredentialContext,
    provider_headers,
    request_provider_credentials,
)
from .broker_payload import (
    parse_credit_inventory,
    sanitize_broker_state,
    sanitize_usage,
)
from .client_http import (
    AccountScanError,
    GuardianSource,
    JsonHttpClient,
    JsonRequest,
    RemoteCallError,
)
from .model_values import utc_now
from .models import (
    AccountDescriptor,
    AccountObservation,
    ConsumeResult,
    PayloadError,
)

if TYPE_CHECKING:
    from .client_http import (
        JsonHttpTransport,
    )
    from .json_contract import JsonObject
    from .models import (
        ResetCredit,
    )


@dataclass(frozen=True, slots=True)
class BrokerProviderConfig:
    """Configure broker and provider HTTP boundaries."""

    broker_url: str
    broker_admin_token: str
    provider_base_url: str = "https://chatgpt.com/backend-api"
    timeout_seconds: float = 20.0


class BrokerProviderSource(GuardianSource):
    """Read broker-managed OAuth state and call the same backend endpoints as Codex."""

    def __init__(
        self,
        config: BrokerProviderConfig,
        *,
        http: JsonHttpTransport | None = None,
    ):
        """Initialize this instance.

        Raises:
            ValueError: If a value violates the required contract.

        """
        if not config.broker_admin_token.strip():
            msg = "broker admin token must not be empty"
            raise ValueError(msg)
        self.broker_url: str = config.broker_url.rstrip("/")
        self.provider_base_url: str = config.provider_base_url.rstrip("/")
        self._broker_headers: dict[str, str] = {
            "Authorization": f"Bearer {config.broker_admin_token}",
            "Accept": "application/json",
            "User-Agent": "pitchai-auth-reset-guardian",
        }
        self._request: JsonHttpTransport = (
            http
            or JsonHttpClient(
                timeout_seconds=config.timeout_seconds,
            ).request
        )

    @override
    def list_accounts(self) -> list[AccountDescriptor]:
        """Return the broker account descriptors.

        Raises:
            PayloadError: If provider data violates the payload contract.

        """
        payload = self._request(
            JsonRequest(
                method="GET",
                url=f"{self.broker_url}/v1/admin/accounts",
                endpoint="broker_list_accounts",
                headers=self._broker_headers,
            ),
        )
        raw_accounts = payload.get("accounts")
        if not isinstance(raw_accounts, list):
            msg = "broker account list is missing accounts"
            raise PayloadError(msg)
        descriptors = [AccountDescriptor.from_broker(raw) for raw in raw_accounts]
        refs = [item.account_ref for item in descriptors]
        if len(refs) != len(set(refs)):
            msg = "broker returned duplicate accounts"
            raise PayloadError(msg)
        return sorted(descriptors, key=lambda item: item.label.lower())

    @override
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        """Refresh broker state and provider capacity for one account.

        Returns:
            The resulting value.

        Raises:
            AccountScanError: If the operation violates its documented contract.

        """
        account_path = urllib.parse.quote(descriptor.broker_account_id, safe="")
        probed = self._request(
            JsonRequest(
                method="POST",
                url=f"{self.broker_url}/v1/admin/accounts/{account_path}/analytics-probe",
                endpoint="broker_analytics_probe",
                headers=self._broker_headers,
            ),
        )
        broker_state = sanitize_broker_state(probed)
        if broker_state.get("availability") == "auth_invalid":
            raise AccountScanError(
                descriptor=descriptor,
                error_code="broker_auth_invalid",
                broker_state=broker_state,
            )
        credentials = request_provider_credentials(
            self._request,
            BrokerCredentialContext(
                self.broker_url,
                account_path,
                descriptor,
                broker_state,
                self._broker_headers,
            ),
        )
        headers = provider_headers(credentials)
        usage = self._request(
            JsonRequest(
                method="GET",
                url=f"{self.provider_base_url}/wham/usage",
                endpoint="provider_usage",
                headers=headers,
            ),
        )
        credit_payload = self._request(
            JsonRequest(
                method="GET",
                url=f"{self.provider_base_url}/wham/rate-limit-reset-credits",
                endpoint="provider_reset_credits",
                headers=headers,
            ),
        )
        available_count, reset_credits = parse_credit_inventory(credit_payload)
        return AccountObservation(
            descriptor=descriptor,
            captured_at=utc_now(),
            broker_state=broker_state,
            usage_state=sanitize_usage(usage),
            available_count=available_count,
            credits=reset_credits,
            credentials=credentials,
        )

    @override
    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        """Consume one exact provider credit with one safe ambiguous retry.

        Returns:
            The resulting value.

        Raises:
            RemoteCallError: If the remote boundary call fails.
            RuntimeError: If the operation cannot satisfy its runtime contract.
            ValueError: If a value violates the required contract.

        """
        if observation.credentials is None:
            msg = "live observation is missing OAuth credentials"
            raise RuntimeError(msg)
        if not idempotency_key:
            msg = "idempotency key must not be empty"
            raise ValueError(msg)
        payload: JsonObject = {
            "redeem_request_id": idempotency_key,
            "credit_id": credit.provider_id,
        }
        last_error: RemoteCallError | None = None
        for _ in range(2):
            try:
                response = self._request(
                    JsonRequest(
                        method="POST",
                        url=(f"{self.provider_base_url}/wham/rate-limit-reset-credits/consume"),
                        endpoint="provider_consume_reset_credit",
                        headers=provider_headers(observation.credentials),
                        payload=payload,
                        ambiguous_on_failure=True,
                    ),
                )
            except RemoteCallError as exc:
                last_error = exc
                if not exc.ambiguous:
                    raise
                continue
            try:
                return ConsumeResult.from_provider(response)
            except PayloadError:
                last_error = RemoteCallError(
                    endpoint="provider_consume_reset_credit",
                    error_code="invalid_result_payload",
                    ambiguous=True,
                )
        if last_error is None:
            msg = "consume retry loop completed without a response or error"
            raise RuntimeError(msg)
        raise last_error
