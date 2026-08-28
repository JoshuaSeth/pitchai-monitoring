# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed runtime boundary for native API integration tests."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from types import TracebackType

    from .mobile_web_runtime import WebApplication
    from .timeseries_types import JsonObject, JsonValue


class TestResponse(Protocol):
    """Minimal response surface inspected by native API tests."""

    @property
    def status_code(self) -> int:
        """Return the response status code."""
        raise NotImplementedError

    def json(self) -> JsonValue:
        """Decode the JSON response body."""
        raise NotImplementedError


class TestClientSurface(Protocol):
    """HTTP operations used inside one application lifespan."""

    def post(self, path: str, *, json: JsonObject) -> TestResponse:
        """Issue one JSON POST request."""
        raise NotImplementedError

    def close(self) -> None:
        """Release the test transport."""
        raise NotImplementedError


class TestClientContext(Protocol):
    """Context manager that runs the application lifespan."""

    def __enter__(self) -> TestClientSurface:
        """Start the application and return its HTTP client."""
        raise NotImplementedError

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Stop the application and release its HTTP client."""
        raise NotImplementedError


class ExceptionInfo[Error: BaseException](Protocol):
    """Typed view of one exception captured by the test runtime."""

    @property
    def value(self) -> Error:
        """Return the captured exception."""
        raise NotImplementedError

    def getrepr(self) -> str:
        """Return a diagnostic representation of the exception."""
        raise NotImplementedError


class RaisesContext[Error: BaseException](Protocol):
    """Context manager that requires one expected exception."""

    def __enter__(self) -> ExceptionInfo[Error]:
        """Begin capturing the expected exception."""
        raise NotImplementedError

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Validate the captured exception."""
        raise NotImplementedError


class _TestClientFactory(Protocol):
    def __call__(self, application: WebApplication) -> TestClientContext:
        """Create one lifespan-aware application client."""
        raise NotImplementedError

    def factory_marker(self) -> None:
        """Identify the dynamic factory contract to static tooling."""
        raise NotImplementedError


class _RaisesFactory(Protocol):
    def __call__[Error: BaseException](
        self,
        exception_type: type[Error],
    ) -> RaisesContext[Error]:
        """Create one typed exception-capture context."""
        raise NotImplementedError

    def factory_marker(self) -> None:
        """Identify the dynamic raises contract to static tooling."""
        raise NotImplementedError


_TESTCLIENT_MODULE = cast(
    "dict[str, object]",
    vars(import_module("fastapi.testclient")),
)
_PYTEST_MODULE = cast("dict[str, object]", vars(import_module("pytest")))

TEST_CLIENT_FACTORY = cast("_TestClientFactory", _TESTCLIENT_MODULE["TestClient"])
RAISES = cast("_RaisesFactory", _PYTEST_MODULE["raises"])
