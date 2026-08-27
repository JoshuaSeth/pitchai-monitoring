# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for hotpath FastAPI route registration."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class FunctionDecorator(Protocol):
    """Typed decorator preserving one endpoint signature."""

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
    """Route-registration surface consumed by hotpath monitoring."""

    def get(self, path: str) -> FunctionDecorator:
        """Create one typed GET route decorator."""
        raise NotImplementedError

    def post(self, path: str) -> FunctionDecorator:
        """Create one typed POST route decorator."""
        raise NotImplementedError


class Application(Protocol):
    """Application surface needed to install hotpath routes."""

    def include_router(self, router_value: Router) -> None:
        """Attach the hotpath router."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _FastAPIModule(NamedTuple):
    APIRouter: Callable[[], object]
    HTTPException: type[Exception]
    Request: type[object]


_FASTAPI = cast("_FastAPIModule", cast("object", import_module("fastapi")))
router = cast("Router", _FASTAPI.APIRouter())

if TYPE_CHECKING:

    class Request(Protocol):
        """Request fields consumed by protected hotpath routes."""

        @property
        def headers(self) -> Mapping[str, str]:
            """Return normalized request headers."""
            raise NotImplementedError

        @property
        def app(self) -> Application:
            """Return the bound application."""
            raise NotImplementedError

    class HTTPExceptionError(Exception):
        """Framework HTTP exception shape used by hotpath routes."""

        status_code: int
        detail: str

        def __init__(self, *, status_code: int, detail: str) -> None:
            """Initialize the typed HTTP error."""
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    HTTPException = HTTPExceptionError

else:
    Request = _FASTAPI.Request
    HTTPException = _FASTAPI.HTTPException
