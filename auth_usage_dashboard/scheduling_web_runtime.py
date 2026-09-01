# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strictly typed dynamic boundary for the scheduling dashboard runtime."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import TracebackType
    from typing import Self, TypedDict, Unpack

    from .service import CapacityService, StateSource
    from .settings import DashboardSettings
    from .timeseries_types import JsonValue


class Application(Protocol):
    """Route-registration surface exposed by the host dashboard."""

    def add_api_route[**Parameters, ReturnValue](
        self,
        path: str,
        endpoint: Callable[Parameters, ReturnValue],
        *,
        methods: list[str],
        response_model: None,
    ) -> None:
        """Register one endpoint without obscuring its signature."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class HeaderMarker(Protocol):
    """Opaque framework marker used as a typed endpoint default."""

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError

    def marker_name(self) -> str:
        """Return the marker contract name."""
        raise NotImplementedError


class HeaderFactory(Protocol):
    """Construct one framework header marker."""

    def __call__(self, default: None, *, alias: str) -> HeaderMarker:
        """Return a marker for one optional proxy header."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class DashboardAppFactory(Protocol):
    """Construct the existing capacity dashboard application."""

    def __call__(
        self,
        settings: DashboardSettings,
        *,
        source: StateSource,
        service: CapacityService,
    ) -> Application:
        """Return the configured base dashboard."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


if TYPE_CHECKING:

    class UvicornOptions(TypedDict):
        """Required production server controls."""

        host: str
        port: int
        access_log: bool
        server_header: bool


class UvicornRunner(Protocol):
    """Serve one scheduling dashboard application."""

    def __call__(
        self,
        application: Application,
        **options: Unpack[UvicornOptions],
    ) -> None:
        """Run the application until shutdown."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Response(Protocol):
    """Synchronous response shape consumed by endpoint tests."""

    status_code: int
    headers: Mapping[str, str]
    text: str

    def json(self) -> JsonValue:
        """Decode the response body."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class JsonResponseFactory(Protocol):
    """Construct one explicit JSON response."""

    def __call__(self, content: JsonValue) -> Response:
        """Return a framework response for strict JSON content."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class TestClient(Protocol):
    """Synchronous client shape consumed by endpoint tests."""

    def __enter__(self) -> Self:
        """Enter the client context."""
        raise NotImplementedError

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Exit the client context."""
        raise NotImplementedError

    def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Issue one local GET request."""
        raise NotImplementedError


class TestClientFactory(Protocol):
    """Construct a synchronous client around the dashboard."""

    def __call__(self, application: Application) -> TestClient:
        """Return a client bound to the supplied application."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _FastAPIModule(NamedTuple):
    Header: HeaderFactory
    HTTPException: type[Exception]


class _DashboardAppModule(NamedTuple):
    create_app: DashboardAppFactory


class _UvicornModule(NamedTuple):
    run: UvicornRunner


class _TestClientModule(NamedTuple):
    TestClient: TestClientFactory


class _ResponsesModule(NamedTuple):
    JSONResponse: JsonResponseFactory


_FASTAPI = cast("_FastAPIModule", cast("object", import_module("fastapi")))
_DASHBOARD_APP = cast(
    "_DashboardAppModule",
    cast("object", import_module("auth_usage_dashboard.app")),
)
_UVICORN = cast("_UvicornModule", cast("object", import_module("uvicorn")))
_RESPONSES = cast(
    "_ResponsesModule",
    cast("object", import_module("fastapi.responses")),
)
_TEST_CLIENT = cast(
    "_TestClientModule",
    cast("object", import_module("fastapi.testclient")),
)

header_factory = cast("HeaderFactory", cast("object", _FASTAPI.Header))
dashboard_app_factory = cast(
    "DashboardAppFactory",
    cast("object", _DASHBOARD_APP.create_app),
)
uvicorn_runner = cast("UvicornRunner", cast("object", _UVICORN.run))
json_response_factory = cast(
    "JsonResponseFactory",
    cast("object", _RESPONSES.JSONResponse),
)
test_client_factory = cast(
    "TestClientFactory",
    cast("object", _TEST_CLIENT.TestClient),
)

if TYPE_CHECKING:

    class HTTPExceptionError(Exception):
        """Framework HTTP exception shape used by the scheduler endpoint."""

        def __init__(self, *, status_code: int, detail: str) -> None:
            """Initialize the typed exception shape."""
            Exception.__init__(self, detail)
            self.status_code: int = status_code
            self.detail: str = detail

    HTTPException = HTTPExceptionError

else:
    HTTPException = _FASTAPI.HTTPException
