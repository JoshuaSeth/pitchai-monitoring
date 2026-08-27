# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strictly typed dynamic boundary for the runtime web framework."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast, overload

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import TracebackType
    from typing import Self

    from httpx import Response

    from .json_types import JsonValue


class FunctionDecorator(Protocol):
    """Typed decorator that preserves an endpoint signature."""

    def __call__[**Parameters, ReturnValue](
        self,
        endpoint: Callable[Parameters, ReturnValue],
    ) -> Callable[Parameters, ReturnValue]:
        """Return the registered endpoint without obscuring its type."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Router(Protocol):
    """Route-registration surface used by monitoring v2."""

    def get(self, path: str, *, response_model: object | None = None) -> FunctionDecorator:
        """Create one typed GET route decorator."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Application(Protocol):
    """Application surface needed by monitoring v2 installation."""

    def include_router(self, router_value: Router) -> None:
        """Attach one monitoring router."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class TestClient(Protocol):
    """Synchronous HTTP client surface used by policy tests."""

    def __enter__(self) -> Self:
        """Enter the synchronous client context."""
        raise NotImplementedError

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Exit the synchronous client context."""
        raise NotImplementedError

    @overload
    def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: JsonValue | None = None,
    ) -> Response:
        ...

    @overload
    def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> Response:
        ...

    def patch(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: JsonValue | None = None,
    ) -> Response:
        """Issue one test PATCH request."""
        raise NotImplementedError


class TestClientFactory(Protocol):
    """Construct a synchronous client around an application."""

    def __call__(self, application: Application) -> TestClient:
        """Return a client bound to the supplied application."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _FastAPIModule(NamedTuple):
    APIRouter: Callable[[], object]
    HTTPException: type[Exception]
    Request: type[object]


class _TestClientModule(NamedTuple):
    TestClient: Callable[[object], object]


_FASTAPI = cast("_FastAPIModule", cast("object", import_module("fastapi")))
_TEST_CLIENT = cast(
    "_TestClientModule",
    cast("object", import_module("fastapi.testclient")),
)
router = cast("Router", _FASTAPI.APIRouter())
test_client_factory = cast("TestClientFactory", cast("object", _TEST_CLIENT.TestClient))

if TYPE_CHECKING:

    class Request(Protocol):
        """Request fields consumed by the protected evidence route."""

        @property
        def headers(self) -> Mapping[str, str]:
            """Return normalized request headers."""
            raise NotImplementedError

        @property
        def app(self) -> Application:
            """Return the bound application object."""
            raise NotImplementedError

    class HTTPExceptionError(Exception):
        """Framework HTTP exception shape used by monitoring v2."""

        status_code: int
        detail: str

        def __init__(self, *, status_code: int, detail: str) -> None:
            """Initialize the typed exception shape."""
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    HTTPException = HTTPExceptionError

else:
    Request = _FASTAPI.Request
    HTTPException = _FASTAPI.HTTPException
