# Copyright (c) 2026 PitchAI. All rights reserved.
"""Durable database-monitor delivery to the signed monitoring Events Bus."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from domain_checks.event_bus import EventBusOutbox, load_event_bus_config

from .incident_events import database_transition_events
from .json_types import normalize_json, object_list

if TYPE_CHECKING:
    from domain_checks.event_bus import EventBusConfig

    from .json_types import JsonInput, JsonObject, JsonValue

LOGGER = logging.getLogger(__name__)


@dataclass
class DatabaseEventBus:
    """One persisted Events Bus producer queue for database transitions."""

    config: EventBusConfig
    outbox: EventBusOutbox

    @classmethod
    def from_state(cls, state: JsonObject) -> DatabaseEventBus | None:
        """Load optional delivery configuration and validate retained entries.

        Returns:
            A configured database producer, or ``None`` when both event-bus
            settings are intentionally absent.

        Raises:
            TypeError: If the persisted outbox is not an array.
        """
        config = load_event_bus_config()
        if config is None:
            return None
        raw_entries = state.get("event_bus_outbox", [])
        if not isinstance(raw_entries, list):
            message = "Persisted database Events Bus outbox must be a list"
            raise TypeError(message)
        entries = object_list(raw_entries)
        if len(entries) != len(raw_entries):
            message = "Persisted database Events Bus outbox entries must be objects"
            raise TypeError(message)
        return cls(config=config, outbox=EventBusOutbox(config, entries=entries))

    def staged_for_cycle(
        self,
        *,
        previous: JsonObject,
        updated: JsonObject,
    ) -> DatabaseEventBus:
        """Clone the retained queue and append this cycle's transitions.

        Returns:
            A staged producer that replaces this instance only after the state
            checkpoint succeeds.
        """
        staged = DatabaseEventBus(
            config=self.config,
            outbox=EventBusOutbox(self.config, entries=self.outbox.to_state()),
        )
        for event in database_transition_events(previous=previous, updated=updated):
            staged.outbox.enqueue(
                event.kind,
                occurred_at=event.occurred_at,
                details=event.details,
            )
        return staged

    def state_value(self) -> JsonValue:
        """Return a strict JSON snapshot suitable for the collector state."""
        return normalize_json(cast("JsonInput", self.outbox.to_state()))

    def flush(self) -> None:
        """Attempt a bounded batch and retain failures for backoff retry."""
        if self.outbox.pending_count == 0:
            return
        attempts = self.outbox.flush_sync()
        for attempt in attempts:
            log = LOGGER.info if attempt.success else LOGGER.warning
            log(
                "database Events Bus delivery success=%s delivery_id=%s status=%s event_id=%s error=%s pending=%s",
                attempt.success,
                attempt.delivery_id,
                attempt.status_code,
                attempt.event_id,
                attempt.error,
                self.outbox.pending_count,
            )
