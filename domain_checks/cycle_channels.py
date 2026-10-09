# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit references to the cycle's existing delivery and dispatch state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .dispatch_state import dispatch_is_enabled
from .dispatch_transport import redact_telegram_response, send_telegram_message, send_telegram_message_chunked

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Sequence
    from types import TracebackType

    from httpx import AsyncClient

    from .dispatch_client import DispatchConfig
    from .dispatch_context import DispatchInputs
    from .dispatch_records import DispatchRecords
    from .event_bus_delivery import JsonObject, JsonValue
    from .telegram import TelegramConfig

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class DispatchResultBoundary:
    """Log completed dispatch failures while preserving cancellation ownership."""

    domain: str

    def __enter__(self) -> Self:
        """Return the boundary for this already completed task."""
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> bool:
        """Return true for ordinary task errors; leave cancellation and system exits loud."""
        if not isinstance(error, Exception):
            return False
        LOGGER.error("Dispatch task crashed domain=%s", self.domain, exc_info=(type(error), error, traceback))
        return True


@dataclass(frozen=True)
class CycleChannels:
    """Use existing transports, task ownership and collections without new routes."""

    client: AsyncClient
    telegram: TelegramConfig
    dispatch_config: DispatchConfig | None
    dispatch_state: JsonObject
    records: DispatchRecords
    tasks: dict[str, asyncio.Task[None]]

    def prune_completed(self) -> None:
        """Consume completed results in snapshot order, retaining interrupted ownership."""
        for domain, task in list(self.tasks.items()):
            if not task.done():
                continue
            with DispatchResultBoundary(domain):
                task.result()
            del self.tasks[domain]

    def dispatch_available(self, key: str, active_message: str) -> bool:
        """Evaluate existing enablement and retain a currently running task.

        Returns:
            True only when the caller can schedule this existing dispatch key.
        """
        if not self.dispatch_config or not dispatch_is_enabled(self.dispatch_config, self.dispatch_state):
            return False
        if key in self.tasks and not self.tasks[key].done():
            LOGGER.info(active_message)
            return False
        return True

    def dispatch_inputs(self) -> DispatchInputs:
        """Build typed arguments referencing the same configured cycle objects.

        Returns:
            The existing transport and mutable record references.

        Raises:
            RuntimeError: No dispatcher was configured by the owning cycle.
        """
        if self.dispatch_config is None:
            message = "Cannot schedule monitoring dispatch without configuration"
            raise RuntimeError(message)
        return {
            "http_client": self.client, "telegram_cfg": self.telegram,
            "dispatch_cfg": self.dispatch_config, "dispatch_state": self.dispatch_state,
            "dispatch_history": self.records.history, "dispatch_last": self.records.last,
            "events": self.records.events,
        }

    async def warning(self, message: str, log_template: str, domains: Sequence[JsonValue]) -> None:
        """Retain chunked delivery, response redaction and the existing warning log."""
        ok_all, responses = await send_telegram_message_chunked(self.client, self.telegram, message)
        LOGGER.warning(log_template, ok_all, redact_telegram_response(responses[-1] if responses else {}), domains[:5])

    async def notice(self, message: str, log_template: str) -> None:
        """Keep chunked warnings whose original log has no domain diagnostic."""
        ok_all, responses = await send_telegram_message_chunked(self.client, self.telegram, message)
        LOGGER.warning(log_template, ok_all, redact_telegram_response(responses[-1] if responses else {}))

    async def recovery(self, message: str, log_template: str) -> None:
        """Retain single-message delivery and its observed result without retries."""
        ok, response = await send_telegram_message(self.client, self.telegram, message)
        LOGGER.info(log_template, ok, redact_telegram_response(response))
