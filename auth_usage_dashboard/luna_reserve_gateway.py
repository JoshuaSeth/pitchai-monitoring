# Copyright (c) 2026 PitchAI. All rights reserved.
"""Infrastructure gateway for the broker's read-only Luna aggregate."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

from .luna_reserve_capacity import build_luna_reserve_snapshot

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType
    from typing import Self, TypedDict, Unpack

    from .timeseries_types import JsonObject, JsonValue


class _HttpResponse(Protocol):
    def raise_for_status(self) -> None:
        """Reject non-successful broker responses."""
        raise NotImplementedError

    def json(self) -> JsonValue:
        """Decode the broker response body."""
        raise NotImplementedError

    def response_marker(self) -> None:
        """Identify the dynamic response boundary."""
        raise NotImplementedError


class _HttpClient(Protocol):
    def __enter__(self) -> Self:
        """Open the bounded client context."""
        raise NotImplementedError

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Close the bounded client context."""
        raise NotImplementedError

    def get(self, path: str) -> _HttpResponse:
        """Read one fixed broker route."""
        raise NotImplementedError

    def client_marker(self) -> None:
        """Identify the dynamic client boundary."""
        raise NotImplementedError


if TYPE_CHECKING:

    class _HttpClientOptions(TypedDict):
        base_url: str
        headers: Mapping[str, str]
        timeout: float


class _HttpClientFactory(Protocol):
    def __call__(self, **options: Unpack[_HttpClientOptions]) -> _HttpClient:
        """Construct one bounded broker client."""
        raise NotImplementedError

    def factory_marker(self) -> None:
        """Identify the dynamic client factory."""
        raise NotImplementedError


class _HttpxModule(NamedTuple):
    Client: _HttpClientFactory


_HTTPX = cast("_HttpxModule", cast("object", import_module("httpx")))
_HTTP_CLIENT_FACTORY = cast("_HttpClientFactory", cast("object", _HTTPX.Client))


def read_luna_reserve_snapshot(
    *,
    broker_url: str,
    admin_token: str,
    request_timeout_seconds: float,
) -> JsonObject:
    """Read and validate the broker's identity-free reserve aggregate.

    Returns:
        A dashboard-specific, identity-free Luna reserve projection.
    """
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "Accept": "application/json",
    }
    with _HTTP_CLIENT_FACTORY(
        base_url=broker_url.rstrip("/"),
        headers=headers,
        timeout=request_timeout_seconds,
    ) as client:
        response = client.get("/v1/admin/capacity")
        response.raise_for_status()
        payload = response.json()
    return build_luna_reserve_snapshot(payload)
