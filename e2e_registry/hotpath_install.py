# Copyright (c) 2026 PitchAI. All rights reserved.
"""Additive production installation for client hotpath monitoring."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, final

from .hotpath_api import router
from .hotpath_config import load_hotpath_config
from .hotpath_events import run_event_worker
from .hotpath_store_schema import ensure_schema

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import NamedTuple, Protocol

    from .hotpath_config import HotpathRuntimeConfig
    from .hotpath_web_runtime import Router
    from .settings import RegistrySettings

    class _RegistryState(NamedTuple):
        settings: RegistrySettings

    class HotpathApplication(Protocol):
        """Established registry application fields used by the installer."""

        @property
        def state(self) -> _RegistryState:
            """Return application runtime state."""
            raise NotImplementedError

        def include_router(self, router_value: Router) -> None:
            """Attach one API router."""
            raise NotImplementedError

        def add_event_handler(
            self,
            event_type: str,
            function: Callable[[], Awaitable[None]],
        ) -> None:
            """Register one asynchronous lifecycle handler."""
            raise NotImplementedError


@final
class HotpathLifecycle:
    """Per-application durable schema and Events Bus worker lifecycle."""

    def __init__(self, config: HotpathRuntimeConfig) -> None:
        """Retain immutable configuration until application startup."""
        self._config = config
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Create the additive schema and launch the outbox worker."""
        await asyncio.to_thread(ensure_schema, self._config.db_path)
        stop = asyncio.Event()
        self._stop = stop
        self._task = asyncio.create_task(
            run_event_worker(self._config.db_path, stop),
            name="hotpath-event-worker",
        )

    async def stop(self) -> None:
        """Drain the bounded worker shutdown path."""
        if self._stop is None or self._task is None:
            return
        self._stop.set()
        await self._task


def install_hotpath_monitoring(application: HotpathApplication) -> None:
    """Attach protected routes and one per-application durable worker."""
    config = load_hotpath_config(application.state.settings)
    lifecycle = HotpathLifecycle(config)
    application.include_router(router)
    application.add_event_handler("startup", lifecycle.start)
    application.add_event_handler("shutdown", lifecycle.stop)
