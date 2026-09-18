# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for hotpath FastAPI route registration."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    type EndpointDecorator[**Parameters, ReturnValue] = Callable[
        [Callable[Parameters, ReturnValue]],
        Callable[Parameters, ReturnValue],
    ]


class Router(Protocol):
    """Route-registration surface consumed by hotpath monitoring."""

    def post[**Parameters, ReturnValue](
        self,
        path: str,
    ) -> EndpointDecorator[Parameters, ReturnValue]:
        """Create one POST route decorator."""
        raise NotImplementedError

    def get[**Parameters, ReturnValue](
        self,
        path: str,
    ) -> EndpointDecorator[Parameters, ReturnValue]:
        """Create one GET route decorator."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Application(Protocol):
    """Host application surface needed by hotpath installation."""

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError

    def include_router(self, router_value: Router) -> None:
        """Attach the hotpath router."""
        raise NotImplementedError


class _FastAPIModule(NamedTuple):
    APIRouter: Callable[[], object]
    Request: type[object]
    HTTPException: type[Exception]


_FASTAPI = cast("_FastAPIModule", cast("object", import_module("fastapi")))
router = cast("Router", _FASTAPI.APIRouter())

if TYPE_CHECKING:

    class Request(NamedTuple):
        """Request fields consumed by protected hotpath routes."""

        app: Application
        headers: Mapping[str, str]

    class HTTPExceptionError(Exception):
        """Framework HTTP exception shape used by hotpath routes."""

        status_code: int
        detail: str

        def __init__(self, *, status_code: int, detail: str) -> None:
            """Initialize the typed HTTP error."""
            self.status_code, self.detail = status_code, detail
            Exception.__init__(self, detail)

    HTTPException = HTTPExceptionError

else:
    Request = _FASTAPI.Request
    HTTPException = _FASTAPI.HTTPException
