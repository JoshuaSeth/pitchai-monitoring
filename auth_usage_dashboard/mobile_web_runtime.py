# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed boundary around runtime-only FastAPI and Starlette objects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue


class WebResponse(Protocol):
    """Minimal response surface returned by native API routes."""

    @property
    def status_code(self) -> int:
        """Return the HTTP status code."""
        raise NotImplementedError

    def set_cookie(self, key: str, value: str) -> None:
        """Represent the shared Starlette response contract."""
        raise NotImplementedError


class WebApplicationState(Protocol):
    """Marker surface for Starlette's dynamically attributed state object."""

    def application_state_marker(self) -> None:
        """Identify the dynamic state contract to static tooling."""
        raise NotImplementedError

    def state_storage_marker(self) -> None:
        """Provide the paired structural marker for state storage."""
        raise NotImplementedError


class WebRouter(Protocol):
    """Decorator surface used by the native-client route module."""

    def post(self, path: str, *, response_model: None) -> RouteDecorator:
        """Register one POST route."""
        raise NotImplementedError

    def get(self, path: str, *, response_model: None) -> RouteDecorator:
        """Represent the paired read-route decorator surface."""
        raise NotImplementedError


class WebApplication(Protocol):
    """Minimal FastAPI application surface used by the wrapper."""

    @property
    def state(self) -> WebApplicationState:
        """Return the dynamic application state container."""
        raise NotImplementedError

    def include_router(self, router: WebRouter) -> None:
        """Install one router."""
        raise NotImplementedError


class WebRequest(Protocol):
    """Minimal Starlette request surface used by route handlers."""

    @property
    def app(self) -> WebApplication:
        """Return the owning application."""
        raise NotImplementedError

    async def json(self) -> JsonValue:
        """Decode one JSON request body."""
        raise NotImplementedError


type RouteFunction = Callable[[WebRequest], Awaitable[WebResponse]]
type RouteDecorator = Callable[[RouteFunction], RouteFunction]


class _RouterFactory(Protocol):
    def __call__(self) -> WebRouter:
        """Create one router."""
        raise NotImplementedError

    def router_factory_marker(self) -> None:
        """Identify this dynamic constructor to static tooling."""
        raise NotImplementedError


class _ResponseFactory(Protocol):
    def __call__(self, content: JsonObject) -> WebResponse:
        """Create one JSON response."""
        raise NotImplementedError

    def response_factory_marker(self) -> None:
        """Identify this dynamic constructor to static tooling."""
        raise NotImplementedError


class _ExceptionFactory(Protocol):
    def __call__(self, *, status_code: int, detail: JsonValue | JsonObject) -> Exception:
        """Create one framework HTTP exception."""
        raise NotImplementedError

    def exception_factory_marker(self) -> None:
        """Identify this dynamic constructor to static tooling."""
        raise NotImplementedError


class _MutableAnnotations(Protocol):
    """Function metadata mutated before FastAPI inspects a route."""

    __annotations__: dict[str, object]

    def mutable_annotations_marker(self) -> None:
        """Identify the mutable function metadata boundary."""
        raise NotImplementedError

    def route_metadata_marker(self) -> None:
        """Provide the paired structural marker for route metadata."""
        raise NotImplementedError


_FASTAPI = cast("dict[str, object]", vars(import_module("fastapi")))
_RESPONSES = cast("dict[str, object]", vars(import_module("fastapi.responses")))
_REQUESTS = cast("dict[str, object]", vars(import_module("starlette.requests")))
ROUTER_FACTORY = cast("_RouterFactory", _FASTAPI["APIRouter"])
JSON_RESPONSE_FACTORY = cast("_ResponseFactory", _RESPONSES["JSONResponse"])
HTTP_EXCEPTION_FACTORY = cast("_ExceptionFactory", _FASTAPI["HTTPException"])
_REQUEST_RUNTIME_TYPE = cast("type[WebRequest]", _REQUESTS["Request"])


def runtime_route(function: RouteFunction) -> RouteFunction:
    """Expose concrete runtime annotations before FastAPI registers a route.

    Returns:
        The same handler with FastAPI-compatible runtime annotations.
    """
    annotated = cast("_MutableAnnotations", function)
    annotated.__annotations__["request"] = _REQUEST_RUNTIME_TYPE
    annotated.__annotations__["return"] = JSON_RESPONSE_FACTORY
    return function
