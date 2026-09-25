# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define guardian source and bounded JSON HTTP contracts."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

from .json_contract import JsonObject, decode_json

_SERVER_ERROR_STATUS = 500

if TYPE_CHECKING:
    from .models import AccountDescriptor, AccountObservation, ConsumeResult, ResetCredit


class RemoteCallError(RuntimeError):
    """A safe remote error that never includes response bodies or credentials."""

    def __init__(self, *, endpoint: str, error_code: str, ambiguous: bool = False):
        """Initialize this instance."""
        super().__init__(f"{endpoint} failed ({error_code})")
        self.endpoint: str = endpoint
        self.error_code: str = error_code
        self.ambiguous: bool = ambiguous


class AccountScanError(RuntimeError):
    """Record a bounded account scan failure."""

    def __init__(
        self,
        *,
        descriptor: AccountDescriptor,
        error_code: str,
        broker_state: JsonObject | None = None,
    ):
        """Initialize this instance."""
        super().__init__(f"account scan failed ({error_code})")
        self.descriptor: AccountDescriptor = descriptor
        self.error_code: str = error_code
        self.broker_state: JsonObject = broker_state or {}


class GuardianSource(ABC):
    """Define account observation and redemption source operations."""

    @abstractmethod
    def list_accounts(self) -> list[AccountDescriptor]:
        """Return the available account descriptors."""
        raise NotImplementedError

    @abstractmethod
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        """Refresh one account observation."""
        raise NotImplementedError

    @abstractmethod
    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        """Consume one exact reset credit."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class JsonRequest:
    """Describe one bounded JSON request without positional ambiguity."""

    method: str
    url: str
    endpoint: str
    headers: dict[str, str]
    payload: JsonObject | None = None
    ambiguous_on_failure: bool = False


type JsonHttpTransport = Callable[[JsonRequest], JsonObject]


def _read_response(
    response: httpx.Response,
    *,
    limit: int,
    endpoint: str,
) -> bytes:
    """Read one bounded streaming HTTP response.

    Returns:
        The resulting value.

    Raises:
        RemoteCallError: If the response exceeds the permitted size.

    """
    raw = bytearray()
    for chunk in response.iter_bytes():
        if len(raw) + len(chunk) > limit:
            raise RemoteCallError(
                endpoint=endpoint,
                error_code="response_too_large",
            )
        raw.extend(chunk)
    return bytes(raw)


def _stream_response(
    request_spec: JsonRequest,
    *,
    body: bytes | None,
    headers: dict[str, str],
    timeout_seconds: float,
) -> bytes:
    """Send one request and drain its bounded response while still streaming.

    Returns:
        The bounded response bytes.

    """
    with httpx.stream(
        request_spec.method,
        request_spec.url,
        content=body,
        headers=headers,
        timeout=timeout_seconds,
    ) as response:
        response.raise_for_status()
        return _read_response(
            response,
            limit=5 * 1024 * 1024,
            endpoint=request_spec.endpoint,
        )


class JsonHttpClient:
    """Send bounded JSON requests without exposing response bodies in errors."""

    def __init__(self, *, timeout_seconds: float = 20.0):
        """Initialize this instance.

        Raises:
            ValueError: If a value violates the required contract.

        """
        if timeout_seconds <= 0:
            msg = "HTTP timeout must be positive"
            raise ValueError(msg)
        self.timeout_seconds: float = timeout_seconds

    def request(self, request_spec: JsonRequest) -> JsonObject:
        """Send one bounded JSON request.

        Returns:
            The resulting value.

        Raises:
            RemoteCallError: If the remote boundary call fails.

        """
        body = None
        request_headers = dict(request_spec.headers)
        if request_spec.payload is not None:
            body = json.dumps(request_spec.payload, separators=(",", ":")).encode(
                "utf-8",
            )
            request_headers["Content-Type"] = "application/json"
        parsed_url = urlsplit(request_spec.url)
        if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname is None:
            raise RemoteCallError(
                endpoint=request_spec.endpoint,
                error_code="invalid_http_url",
            )
        try:
            raw = _stream_response(
                request_spec,
                body=body,
                headers=request_headers,
                timeout_seconds=self.timeout_seconds,
            )
        except httpx.HTTPStatusError as exc:
            raise RemoteCallError(
                endpoint=request_spec.endpoint,
                error_code=f"http_{exc.response.status_code}",
                ambiguous=(request_spec.ambiguous_on_failure and exc.response.status_code >= _SERVER_ERROR_STATUS),
            ) from None
        except httpx.HTTPError as exc:
            raise RemoteCallError(
                endpoint=request_spec.endpoint,
                error_code=f"transport_{type(exc).__name__}",
                ambiguous=request_spec.ambiguous_on_failure,
            ) from None
        return self.decode_response(raw, request_spec=request_spec)

    @staticmethod
    def decode_response(
        raw: bytes,
        *,
        request_spec: JsonRequest,
    ) -> JsonObject:
        """Decode one bounded response using its safe request context.

        Returns:
            The resulting value.

        Raises:
            RemoteCallError: If the remote boundary call fails.

        """
        try:
            decoded = decode_json(raw)
        except ValueError:
            raise RemoteCallError(
                endpoint=request_spec.endpoint,
                error_code="invalid_json",
                ambiguous=request_spec.ambiguous_on_failure,
            ) from None
        if not isinstance(decoded, dict):
            raise RemoteCallError(
                endpoint=request_spec.endpoint,
                error_code="invalid_payload",
                ambiguous=request_spec.ambiguous_on_failure,
            )
        return decoded
