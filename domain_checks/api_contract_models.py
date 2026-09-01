# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed data contracts for API monitoring checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, Protocol

if TYPE_CHECKING:
    from .api_contract_coordination import ApiContractCoordinator

ApiValue = object
ApiConfig = dict[str, ApiValue]
ApiDetails = dict[str, ApiValue]


class ApiHttpResponse(Protocol):
    """The response surface required by API contract monitoring."""

    status_code: int
    headers: dict[str, str]

    @property
    def url(self) -> ApiValue:
        """Return the final response URL.

        Raises:
            NotImplementedError: Protocol declarations have no implementation.
        """
        raise NotImplementedError

    def json(self) -> ApiValue:
        """Decode and return the response body.

        Raises:
            NotImplementedError: Protocol declarations have no implementation.
        """
        raise NotImplementedError

    def read(self) -> bytes:
        """Return the buffered response body.

        Raises:
            NotImplementedError: Protocol declarations have no implementation.
        """
        raise NotImplementedError


class ApiHttpClient(Protocol):
    """The asynchronous HTTP surface required by API contract monitoring."""

    async def request(self, *args: ApiValue, **kwargs: ApiValue) -> ApiHttpResponse:
        """Execute one HTTP request and return its response.

        Raises:
            NotImplementedError: Protocol declarations have no implementation.
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """Close the asynchronous client.

        Raises:
            NotImplementedError: Protocol declarations have no implementation.
        """
        raise NotImplementedError


class ApiContractCheckResult(NamedTuple):
    """One independently attributed API contract result."""

    domain: str
    name: str
    ok: bool
    url: str
    status_code: int | None
    elapsed_ms: float | None
    error: str | None
    details: ApiDetails
    coordination_key: str | None = None


class ApiRequestSpec(NamedTuple):
    """A normalized request ready for the HTTP client."""

    method: str
    url: str
    json_body: ApiValue | None
    text_body: str | None
    headers: dict[str, str]


class ApiResponseExpectation(NamedTuple):
    """The response assertions for one API check."""

    statuses: tuple[int, ...]
    content_type: str | None
    required_paths: tuple[str, ...]
    equal_paths: ApiDetails
    max_elapsed_ms: float | None


class ApiContractSpec(NamedTuple):
    """A normalized API contract check."""

    name: str
    coordination_key: str | None
    request: ApiRequestSpec
    expectation: ApiResponseExpectation


class ApiExecutionContext(NamedTuple):
    """Shared dependencies for one group of API checks."""

    client: ApiHttpClient
    coordinator: ApiContractCoordinator
    domain: str
    base_url: str
    timeout_seconds: float
