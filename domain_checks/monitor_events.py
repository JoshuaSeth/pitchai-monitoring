# Copyright (c) 2026 PitchAI. All rights reserved.
"""Durable monitoring events and Events Bus outbox delivery."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_checks.monitor_state import write_state_atomic
from domain_checks.monitor_state_payload import build_state_payload

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from domain_checks.event_bus import EventBusOutbox
    from domain_checks.monitor_runtime_state import RuntimeState
    from domain_checks.types import JsonObject, JsonValue

LOGGER = logging.getLogger("service-monitoring")
_MAX_EVENTS = 10_000
_RETAINED_EVENTS = 8_000


@dataclass
class MonitorEvents:
    """Record transitions locally and durably enqueue configured bus events."""

    state: RuntimeState
    outbox: EventBusOutbox | None
    state_path: Path | None

    def append(self, kind: str, *, occurred_at: float | None = None, **details: JsonValue) -> None:
        """Append one transition and immediately persist a changed outbox."""
        timestamp = occurred_at if occurred_at is not None else time.time()
        entry: JsonObject = {"ts": timestamp, "kind": kind, **details}
        self.state.collections.events.append(entry)
        if len(self.state.collections.events) > _MAX_EVENTS:
            del self.state.collections.events[:-_RETAINED_EVENTS]
        if self.outbox is not None:
            self.outbox.enqueue(kind, occurred_at=timestamp, details=dict(details))
            self.persist()

    def persist(self) -> bool:
        """Write current state and update the persistence failure streak.

        Returns:
            Whether state is absent by policy or was persisted successfully.
        """
        if self.state_path is None:
            return True
        try:
            write_state_atomic(self.state_path, build_state_payload(self.state, self.outbox))
        except (OSError, TypeError, ValueError) as exc:
            self.state.metadata.state_write_fail_streak += 1
            LOGGER.warning("Failed to write state file path=%s error=%s", self.state_path, exc)
            return False
        self.state.metadata.state_write_fail_streak = 0
        return True

    async def flush(self, http_client: httpx.AsyncClient) -> None:
        """Deliver pending Events Bus records and log every attempt."""
        if self.outbox is None or self.outbox.pending_count == 0:
            return
        for attempt in await self.outbox.flush(http_client):
            log = LOGGER.info if attempt.success else LOGGER.warning
            log(
                "Events Bus success=%s delivery_id=%s status=%s event_id=%s error=%s pending=%s",
                attempt.success,
                attempt.delivery_id,
                attempt.status_code,
                attempt.event_id,
                attempt.error,
                self.outbox.pending_count,
            )
        self.persist()


def persisted_outbox_entries(value: JsonValue) -> list[JsonObject]:
    """Validate the persisted Events Bus outbox shape without narrowing errors.

    Returns:
        The validated persisted event objects.

    Raises:
        TypeError: The outbox or one of its entries has an invalid type.
    """
    if not isinstance(value, list):
        message = "Persisted PitchAI Events Bus outbox must be a list"
        raise TypeError(message)
    if not all(isinstance(entry, dict) for entry in value):
        message = "Persisted PitchAI Events Bus outbox entries must be mappings"
        raise TypeError(message)
    return [entry for entry in value if isinstance(entry, dict)]
