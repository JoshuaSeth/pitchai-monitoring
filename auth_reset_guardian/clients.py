from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .models import (
    AccountDescriptor,
    AccountObservation,
    ConsumeResult,
    PayloadError,
    ProviderCredentials,
    ResetCredit,
    safe_label,
    utc_now,
)


class RemoteCallError(RuntimeError):
    """A safe remote error that never includes response bodies or credentials."""

    def __init__(self, *, endpoint: str, error_code: str, ambiguous: bool = False):
        super().__init__(f"{endpoint} failed ({error_code})")
        self.endpoint = endpoint
        self.error_code = error_code
        self.ambiguous = ambiguous


class AccountScanError(RuntimeError):
    def __init__(
        self,
        *,
        descriptor: AccountDescriptor,
        error_code: str,
        broker_state: dict[str, Any] | None = None,
    ):
        super().__init__(f"account scan failed ({error_code})")
        self.descriptor = descriptor
        self.error_code = error_code
        self.broker_state = broker_state or {}


class GuardianSource(ABC):
    @abstractmethod
    def list_accounts(self) -> list[AccountDescriptor]:
        raise NotImplementedError

    @abstractmethod
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        raise NotImplementedError

    @abstractmethod
    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        raise NotImplementedError


class JsonHttpClient:
    def __init__(self, *, timeout_seconds: float = 20.0):
        if timeout_seconds <= 0:
            raise ValueError("HTTP timeout must be positive")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        *,
        method: str,
        url: str,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        ambiguous_on_failure: bool = False,
    ) -> dict[str, Any]:
        body = None
        request_headers = dict(headers)
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(5 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            raise RemoteCallError(
                endpoint=endpoint,
                error_code=f"http_{exc.code}",
                ambiguous=ambiguous_on_failure and exc.code >= 500,
            ) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            raise RemoteCallError(
                endpoint=endpoint,
                error_code=f"transport_{type(exc).__name__}",
                ambiguous=ambiguous_on_failure,
            ) from None
        if len(raw) > 5 * 1024 * 1024:
            raise RemoteCallError(endpoint=endpoint, error_code="response_too_large")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RemoteCallError(
                endpoint=endpoint,
                error_code="invalid_json",
                ambiguous=ambiguous_on_failure,
            ) from None
        if not isinstance(decoded, dict):
            raise RemoteCallError(
                endpoint=endpoint,
                error_code="invalid_payload",
                ambiguous=ambiguous_on_failure,
            )
        return decoded


class BrokerProviderSource(GuardianSource):
    """Read broker-managed OAuth state and call the same backend endpoints as Codex."""

    def __init__(
        self,
        *,
        broker_url: str,
        broker_admin_token: str,
        provider_base_url: str = "https://chatgpt.com/backend-api",
        timeout_seconds: float = 20.0,
        http: JsonHttpClient | None = None,
    ):
        if not broker_admin_token.strip():
            raise ValueError("broker admin token must not be empty")
        self.broker_url = broker_url.rstrip("/")
        self.provider_base_url = provider_base_url.rstrip("/")
        self._broker_headers = {
            "Authorization": f"Bearer {broker_admin_token}",
            "Accept": "application/json",
            "User-Agent": "pitchai-auth-reset-guardian",
        }
        self.http = http or JsonHttpClient(timeout_seconds=timeout_seconds)

    def list_accounts(self) -> list[AccountDescriptor]:
        payload = self.http.request(
            method="GET",
            url=f"{self.broker_url}/v1/admin/accounts",
            endpoint="broker_list_accounts",
            headers=self._broker_headers,
        )
        raw_accounts = payload.get("accounts")
        if not isinstance(raw_accounts, list):
            raise PayloadError("broker account list is missing accounts")
        descriptors = [AccountDescriptor.from_broker(raw) for raw in raw_accounts]
        refs = [item.account_ref for item in descriptors]
        if len(refs) != len(set(refs)):
            raise PayloadError("broker returned duplicate accounts")
        return sorted(descriptors, key=lambda item: item.label.lower())

    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        account_path = urllib.parse.quote(descriptor.broker_account_id, safe="")
        probed = self.http.request(
            method="POST",
            url=f"{self.broker_url}/v1/admin/accounts/{account_path}/analytics-probe",
            endpoint="broker_analytics_probe",
            headers=self._broker_headers,
        )
        broker_state = _sanitize_broker_state(probed)
        if broker_state.get("availability") == "auth_invalid":
            raise AccountScanError(
                descriptor=descriptor,
                error_code="broker_auth_invalid",
                broker_state=broker_state,
            )

        auth_json = self.http.request(
            method="GET",
            url=f"{self.broker_url}/v1/admin/accounts/{account_path}/auth.json",
            endpoint="broker_export_auth",
            headers=self._broker_headers,
        )
        tokens = auth_json.get("tokens")
        if not isinstance(tokens, dict):
            raise AccountScanError(
                descriptor=descriptor,
                error_code="broker_auth_tokens_missing",
                broker_state=broker_state,
            )
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")
        if not isinstance(access_token, str) or not access_token.strip():
            raise AccountScanError(
                descriptor=descriptor,
                error_code="broker_access_token_missing",
                broker_state=broker_state,
            )
        if not isinstance(account_id, str) or not account_id.strip():
            raise AccountScanError(
                descriptor=descriptor,
                error_code="broker_chatgpt_account_id_missing",
                broker_state=broker_state,
            )
        credentials = ProviderCredentials(
            access_token=access_token.strip(),
            account_id=account_id.strip(),
        )
        provider_headers = self._provider_headers(credentials)
        usage = self.http.request(
            method="GET",
            url=f"{self.provider_base_url}/wham/usage",
            endpoint="provider_usage",
            headers=provider_headers,
        )
        credit_payload = self.http.request(
            method="GET",
            url=f"{self.provider_base_url}/wham/rate-limit-reset-credits",
            endpoint="provider_reset_credits",
            headers=provider_headers,
        )
        available_count, credits = _parse_credit_inventory(credit_payload)
        return AccountObservation(
            descriptor=descriptor,
            captured_at=utc_now(),
            broker_state=broker_state,
            usage_state=_sanitize_usage(usage),
            available_count=available_count,
            credits=credits,
            credentials=credentials,
        )

    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        if observation.credentials is None:
            raise RuntimeError("live observation is missing OAuth credentials")
        if not idempotency_key:
            raise ValueError("idempotency key must not be empty")
        payload = {
            "redeem_request_id": idempotency_key,
            "credit_id": credit.provider_id,
        }
        last_error: RemoteCallError | None = None
        # A lost response is ambiguous. One immediate retry with the exact same
        # idempotency key is safe; later runs also resume that key from SQLite.
        for _ in range(2):
            try:
                response = self.http.request(
                    method="POST",
                    url=f"{self.provider_base_url}/wham/rate-limit-reset-credits/consume",
                    endpoint="provider_consume_reset_credit",
                    headers=self._provider_headers(observation.credentials),
                    payload=payload,
                    ambiguous_on_failure=True,
                )
                return ConsumeResult.from_provider(response)
            except RemoteCallError as exc:
                last_error = exc
                if not exc.ambiguous:
                    raise
        assert last_error is not None
        raise last_error

    @staticmethod
    def _provider_headers(credentials: ProviderCredentials) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {credentials.access_token}",
            "ChatGPT-Account-Id": credentials.account_id,
            "Accept": "application/json",
            "User-Agent": "pitchai-auth-reset-guardian",
        }


def _sanitize_broker_state(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state")
    if not isinstance(state, dict):
        raise PayloadError("broker analytics probe is missing state")
    analytics = state.get("analytics")
    analytics = analytics if isinstance(analytics, dict) else {}
    raw_errors = analytics.get("errors")
    errors = (
        {str(key)[:80]: str(value)[:80] for key, value in raw_errors.items()}
        if isinstance(raw_errors, dict)
        else {}
    )
    return {
        "availability": _optional_text(state.get("availability"), 80),
        "last_probe_at": _optional_text(state.get("last_probe_at"), 80),
        "cooldown_until": _optional_text(state.get("cooldown_until"), 80),
        "analytics_last_probe_at": _optional_text(analytics.get("last_probe_at"), 80),
        "analytics_errors": errors,
    }


def _sanitize_usage(payload: dict[str, Any]) -> dict[str, Any]:
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise PayloadError("provider usage response is missing rate_limit")
    reset_summary = payload.get("rate_limit_reset_credits")
    reset_summary = reset_summary if isinstance(reset_summary, dict) else {}
    return {
        "allowed": bool(rate_limit.get("allowed", False)),
        "limit_reached": bool(rate_limit.get("limit_reached", False)),
        "primary_window": _sanitize_window(rate_limit.get("primary_window")),
        "secondary_window": _sanitize_window(rate_limit.get("secondary_window")),
        "available_reset_count": _optional_nonnegative_int(reset_summary.get("available_count")),
        "applicable_reset_count": _optional_nonnegative_int(
            reset_summary.get("applicable_available_count")
        ),
    }


def _sanitize_window(value: object) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PayloadError("provider rate-limit window must be an object or null")
    result: dict[str, int] = {}
    for key in (
        "limit_window_seconds",
        "reset_after_seconds",
        "reset_at",
        "used_percent",
    ):
        parsed = _optional_nonnegative_int(value.get(key))
        if parsed is not None:
            result[key] = parsed
    return result


def _parse_credit_inventory(payload: dict[str, Any]) -> tuple[int, tuple[ResetCredit, ...]]:
    available_count = _optional_nonnegative_int(payload.get("available_count"))
    if available_count is None:
        raise PayloadError("provider reset-credit response is missing available_count")
    raw_credits = payload.get("credits")
    if not isinstance(raw_credits, list):
        raise PayloadError("provider reset-credit response is missing credits")
    if len(raw_credits) > 1000:
        raise PayloadError("provider reset-credit response exceeds the safety limit")
    credits = tuple(ResetCredit.from_provider(raw) for raw in raw_credits)
    refs = [credit.credit_ref for credit in credits]
    if len(refs) != len(set(refs)):
        raise PayloadError("provider reset-credit response contains duplicate IDs")
    return available_count, tuple(
        sorted(
            credits,
            key=lambda credit: (
                credit.expires_at is None,
                credit.expires_at or datetime.max.replace(tzinfo=utc_now().tzinfo),
            ),
        )
    )


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _optional_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


class SimulationSource(GuardianSource):
    """In-memory source used to exercise expiry and redemption without a network."""

    def __init__(
        self,
        fixture: dict[str, Any],
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        raw_accounts = fixture.get("accounts")
        if not isinstance(raw_accounts, list):
            raise PayloadError("simulation fixture must contain an accounts list")
        self._accounts = deepcopy(raw_accounts)
        self._clock = clock or utc_now
        self.consume_calls: list[dict[str, str]] = []
        self.refresh_calls: dict[str, int] = {}

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> "SimulationSource":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PayloadError("simulation fixture root must be an object")
        return cls(payload, clock=clock)

    def list_accounts(self) -> list[AccountDescriptor]:
        descriptors: list[AccountDescriptor] = []
        for index, account in enumerate(self._accounts):
            if not isinstance(account, dict):
                raise PayloadError("simulation account must be an object")
            label = safe_label(account.get("label"))
            descriptors.append(
                AccountDescriptor(
                    broker_account_id=f"simulation:{index}:{label}",
                    label=label,
                    enabled=bool(account.get("enabled", True)),
                    priority=index,
                )
            )
        return descriptors

    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        account = self._find(descriptor)
        self.refresh_calls[descriptor.account_ref] = self.refresh_calls.get(descriptor.account_ref, 0) + 1
        fail_on_refresh = account.get("fail_on_refresh")
        if isinstance(fail_on_refresh, int) and self.refresh_calls[descriptor.account_ref] >= fail_on_refresh:
            raise AccountScanError(
                descriptor=descriptor,
                error_code="simulation_refresh_failure",
                broker_state={"availability": "unknown"},
            )
        credit_payload = account.get("credit_inventory")
        if not isinstance(credit_payload, dict):
            raise PayloadError("simulation account is missing credit_inventory")
        available_count, credits = _parse_credit_inventory(credit_payload)
        usage = account.get("usage")
        if not isinstance(usage, dict):
            raise PayloadError("simulation account is missing usage")
        return AccountObservation(
            descriptor=descriptor,
            captured_at=self._clock(),
            broker_state={"availability": str(account.get("broker_availability", "available"))},
            usage_state=_sanitize_usage(usage),
            available_count=available_count,
            credits=credits,
            credentials=None,
        )

    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        account = self._find(observation.descriptor)
        self.consume_calls.append(
            {
                "account_ref": observation.descriptor.account_ref,
                "credit_ref": credit.credit_ref,
                "provider_id": credit.provider_id,
                "idempotency_key": idempotency_key,
            }
        )
        outcomes = account.get("consume_outcomes")
        raw_outcome: object = None
        if isinstance(outcomes, dict):
            raw_outcome = outcomes.get(credit.provider_id)
            if isinstance(raw_outcome, list):
                raw_outcome = raw_outcome.pop(0) if raw_outcome else None
        if raw_outcome is None:
            raw_outcome = {"code": "nothing_to_reset", "windows_reset": 0}
        result = ConsumeResult.from_provider(raw_outcome)
        if result.code in {"reset", "already_redeemed", "no_credit"}:
            inventory = account["credit_inventory"]
            inventory["credits"] = [
                item for item in inventory["credits"] if item.get("id") != credit.provider_id
            ]
            inventory["available_count"] = sum(
                1 for item in inventory["credits"] if item.get("status") == "available"
            )
        return result

    def remove_credit_before_next_refresh(self, *, label: str, provider_id: str) -> None:
        account = next(item for item in self._accounts if item.get("label") == label)
        inventory = account["credit_inventory"]
        inventory["credits"] = [item for item in inventory["credits"] if item.get("id") != provider_id]
        inventory["available_count"] = len(inventory["credits"])

    def _find(self, descriptor: AccountDescriptor) -> dict[str, Any]:
        for account in self._accounts:
            if account.get("label") == descriptor.label:
                return account
        raise PayloadError("simulation descriptor has no matching account")
