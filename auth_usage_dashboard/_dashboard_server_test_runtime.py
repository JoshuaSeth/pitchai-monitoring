# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed in-process uvicorn boundary that serves the dashboard for browser tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from typing import TypedDict, Unpack

    from .scheduling_web_runtime import Application

    class UvicornOptions(TypedDict):
        """Loopback server controls for one browser test."""

        host: str
        port: int
        access_log: bool
        log_level: str


LOOPBACK = "127.0.0.1"
STARTUP_POLLS = 100
STARTUP_POLL_SECONDS = 0.05


class ListeningSocket(Protocol):
    """Bound listening socket of the test server."""

    def getsockname(self) -> tuple[str, int]:
        """Return the bound IPv4 host and port."""
        raise NotImplementedError

    def fileno(self) -> int:
        """Return the socket file descriptor."""
        raise NotImplementedError


class ListeningServer(Protocol):
    """Event-loop server accepting dashboard connections."""

    @property
    def sockets(self) -> tuple[ListeningSocket, ...]:
        """Return the bound listening sockets."""
        raise NotImplementedError

    def close(self) -> None:
        """Stop accepting connections."""
        raise NotImplementedError


class UvicornConfig(Protocol):
    """Loaded uvicorn server configuration."""

    host: str
    port: int

    def load(self) -> None:
        """Load the application and protocol classes."""
        raise NotImplementedError

    def configure_logging(self) -> None:
        """Apply the configured log level."""
        raise NotImplementedError


class UvicornServer(Protocol):
    """In-process uvicorn server sharing the test event loop."""

    started: bool
    should_exit: bool
    servers: list[ListeningServer]

    async def serve(self) -> None:
        """Run startup, the accept loop, and shutdown."""
        raise NotImplementedError

    async def shutdown(self) -> None:
        """Close listeners and run the lifespan shutdown."""
        raise NotImplementedError


class _UvicornConfigFactory(Protocol):
    def __call__(self, app: Application, **options: Unpack[UvicornOptions]) -> UvicornConfig:
        """Configure one server for the dashboard application."""
        raise NotImplementedError

    def factory_marker(self) -> None:
        """Identify the dynamic configuration contract to static tooling."""
        raise NotImplementedError


_UVICORN_MODULE = cast("dict[str, object]", vars(import_module("uvicorn")))
_UVICORN_CONFIG = cast("_UvicornConfigFactory", _UVICORN_MODULE["Config"])
_UVICORN_SERVER = cast("Callable[[UvicornConfig], UvicornServer]", _UVICORN_MODULE["Server"])


@asynccontextmanager
async def serve_dashboard(application: Application) -> AsyncGenerator[str]:
    """Serve the dashboard on an ephemeral loopback port until the context exits.

    Yields:
        The dashboard base URL.

    Raises:
        RuntimeError: If the server does not finish starting.
    """
    config = _UVICORN_CONFIG(application, host=LOOPBACK, port=0, access_log=False, log_level="warning")
    server = _UVICORN_SERVER(config)
    serving = asyncio.create_task(server.serve())
    for _ in range(STARTUP_POLLS):
        if server.started or serving.done():
            break
        await asyncio.sleep(STARTUP_POLL_SECONDS)
    if not server.started:
        server.should_exit = True
        await serving
        message = "auth usage dashboard did not start"
        raise RuntimeError(message)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://{LOOPBACK}:{port}"
    finally:
        server.should_exit = True
        await serving
