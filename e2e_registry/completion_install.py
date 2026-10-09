# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reviewed registry-source configuration and bounded application lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, cast, final
from uuid import UUID

from .completion_capture import RegistrySource, install_capture
from .completion_delivery import run_completion_worker

if TYPE_CHECKING:
    from .hotpath_install import HotpathApplication
    from .hotpath_types import JsonValue


def reviewed_sources(document: str) -> tuple[RegistrySource, ...]:
    """Read explicit registry identities without inferring Engine ownership.

    Returns:
        Exactly the reviewed source pairs, with an empty list disabling capture.

    Raises:
        TypeError: Configuration has the wrong JSON types.
        ValueError: Configuration is malformed, noncanonical or duplicated.
    """
    records = cast("JsonValue", json.loads(document))
    if not isinstance(records, list):
        message = "Registry completion sources must be a JSON list."
        raise TypeError(message)
    sources: list[RegistrySource] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"tenant_id", "test_id"}:
            message = "Each registry source requires only tenant_id and test_id."
            raise ValueError(message)
        tenant_id, test_id = record["tenant_id"], record["test_id"]
        if not isinstance(tenant_id, str) or not isinstance(test_id, str):
            message = "Registry source identities must be strings."
            raise TypeError(message)
        if str(UUID(tenant_id)) != tenant_id or str(UUID(test_id)) != test_id:
            message = "Registry source identities must be canonical UUIDs."
            raise ValueError(message)
        source = RegistrySource(tenant_id, test_id)
        if source in sources:
            message = "Registry completion source is duplicated."
            raise ValueError(message)
        sources.append(source)
    return tuple(sources)


@final
class CompletionLifecycle:
    """Capture and deliver original results independently of incident dispatch."""

    def __init__(self, db_path: str, sources: tuple[RegistrySource, ...]) -> None:
        """Retain reviewed configuration without touching the database yet."""
        self._db_path = db_path
        self._sources = sources
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Replace only capture scope, then drain retained original obligations."""
        await asyncio.to_thread(install_capture, self._db_path, self._sources)
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(
            run_completion_worker(self._db_path, self._stop), name="registry-completion-events",
        )

    async def stop(self) -> None:
        """Finish any bounded delivery before application shutdown."""
        if self._stop is not None and self._task is not None:
            self._stop.set()
            await self._task


def install_registry_completions(application: HotpathApplication) -> None:
    """Install future-only capture after the registry's original schema startup."""
    sources = reviewed_sources(os.environ.get("PITCHAI_REGISTRY_COMPLETION_SOURCES", "[]"))
    lifecycle = CompletionLifecycle(application.state.settings.db_path, sources)
    application.add_event_handler("startup", lifecycle.start)
    application.add_event_handler("shutdown", lifecycle.stop)
