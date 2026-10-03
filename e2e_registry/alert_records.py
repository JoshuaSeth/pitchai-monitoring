# Copyright (c) 2026 PitchAI. All rights reserved.
"""Persist an existing registry dispatch observation before optional forwarding."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from . import db as dbm

if TYPE_CHECKING:
    from domain_checks.event_bus_delivery import JsonObject

    from .settings import RegistrySettings

LOGGER = logging.getLogger("e2e-registry")


@dataclass(frozen=True)
class DispatchRecord:
    """The original DB record plus its existing terminal notice decision."""

    state_key: str
    bundle: str
    ui: str
    queue_state: str
    agent_message: str | None
    error_message: str | None

    async def persist(self, settings: RegistrySettings, context: JsonObject | None) -> None:
        """Retain best-effort DB persistence while propagating cancellation."""
        write = asyncio.create_task(self.write(settings, context))
        results = await asyncio.gather(write, return_exceptions=True)
        if write.cancelled():
            await write
        result = results[0]
        if isinstance(result, Exception):
            LOGGER.error("Failed to persist dispatch run record", exc_info=(type(result), result, result.__traceback__))
        elif isinstance(result, BaseException):
            raise result

    async def write(self, settings: RegistrySettings, context: JsonObject | None) -> None:
        """Use the existing worker-thread DB operation and unmodified schema."""
        _ = cast("JsonObject", await asyncio.to_thread(
            dbm.insert_dispatch_run, settings, state_key=self.state_key, bundle=self.bundle,
            ui_url=self.ui, queue_state=self.queue_state, agent_message=self.agent_message,
            error_message=self.error_message, context=context or {},
        ))

    def notice(self) -> str | None:
        """Choose the existing message, failure or processed-without-message result.

        Returns:
            Text to forward, or None for processed runs without an agent message.
        """
        if self.agent_message:
            return f"Dispatcher triage completed:\n{self.ui}\n\n{self.agent_message}".strip()
        if self.queue_state != "processed":
            error = self.error_message or ""
            return f"Dispatcher triage failed state={self.queue_state} ui={self.ui}\nError: {error[:500]}"
        return None
