# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strictly typed dynamic boundary around the FastAPI objects of the capacity dashboard.

FastAPI is a runtime-only dependency of the dashboard, so its application,
header marker, HTTP exception, and request class are resolved here once and
exposed through the narrow protocols the dashboard actually uses.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractAsyncContextManager
    from typing import NotRequired, TypedDict, Unpack

    from starlette.datastructures import State
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.staticfiles import StaticFiles

type HttpMiddleware = Callable[[Request, RequestResponseEndpoint], Awaitable[Response]]
type Lifespan = Callable[[DashboardApplication], AbstractAsyncContextManager[None]]

if TYPE_CHECKING:

    class RouteOptions(TypedDict):
        """Registration options of one dashboard endpoint."""

        methods: list[str]
        response_model: None
        response_class: NotRequired[type[Response]]

    class ApplicationOptions(TypedDict):
        """Construction options of the dashboard application."""

        title: str
        docs_url: None
        redoc_url: None
        openapi_url: None
        lifespan: Lifespan


class DashboardApplication(Protocol):
    """FastAPI application surface used to assemble the dashboard."""

    @property
    def state(self) -> State:
        """Return the application state shared with route dependencies."""
        raise NotImplementedError

    def mount(self, path: str, app: StaticFiles, *, name: str) -> None:
        """Serve static assets below one path prefix."""
        raise NotImplementedError

    def middleware(self, middleware_type: str) -> Callable[[HttpMiddleware], HttpMiddleware]:
        """Return the decorator that installs one HTTP middleware."""
        raise NotImplementedError

    def add_api_route[**Parameters, ReturnValue](
        self,
        path: str,
        endpoint: Callable[Parameters, ReturnValue],
        **options: Unpack[RouteOptions],
    ) -> None:
        """Register one endpoint whose runtime annotations FastAPI inspects."""
        raise NotImplementedError


class _ApplicationFactory(Protocol):
    def __call__(self, **options: Unpack[ApplicationOptions]) -> DashboardApplication:
        """Create one FastAPI application without interactive documentation."""
        raise NotImplementedError

    def application_factory_marker(self) -> None:
        """Identify the dynamic application constructor to static tooling."""
        raise NotImplementedError


class HeaderMarker(Protocol):
    """Opaque FastAPI marker that binds an endpoint parameter to one request header."""

    def header_marker(self) -> None:
        """Identify the dynamic header marker to static tooling."""
        raise NotImplementedError

    def parameter_marker(self) -> None:
        """Provide the paired structural marker for endpoint parameters."""
        raise NotImplementedError


class _HeaderFactory(Protocol):
    def __call__(self, default: None, *, alias: str) -> HeaderMarker:
        """Create the marker for one optional header."""
        raise NotImplementedError

    def header_factory_marker(self) -> None:
        """Identify the dynamic header constructor to static tooling."""
        raise NotImplementedError


class _ExceptionFactory(Protocol):
    def __call__(self, *, status_code: int, detail: str) -> Exception:
        """Create one HTTP exception rendered as a JSON ``detail`` response."""
        raise NotImplementedError

    def exception_factory_marker(self) -> None:
        """Identify the dynamic exception constructor to static tooling."""
        raise NotImplementedError


_FASTAPI = cast("dict[str, object]", vars(import_module("fastapi")))
APPLICATION_FACTORY = cast("_ApplicationFactory", _FASTAPI["FastAPI"])
HEADER_FACTORY = cast("_HeaderFactory", _FASTAPI["Header"])
HTTP_EXCEPTION_FACTORY = cast("_ExceptionFactory", _FASTAPI["HTTPException"])
REQUEST_TYPE = cast("type[Request]", _FASTAPI["Request"])
