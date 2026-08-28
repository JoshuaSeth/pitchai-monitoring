# Copyright (c) 2026 PitchAI. All rights reserved.
"""Durable database-monitor delivery to the signed monitoring Events Bus."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from .event_bus_runtime import (
    DELIVERY_RUNTIME,
    EVENT_BUS_RUNTIME,
)
from .incident_events import database_transition_events
from .json_types import (
    float_value,
    int_value,
    json_object,
    normalize_json,
    object_list,
    optional_object,
    text_value,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from httpx import BaseTransport

    from .event_bus_runtime import DeliveryAttempt, EventBusConfig
    from .json_types import JsonInput, JsonObject, JsonValue


class IncidentEvent(Protocol):
    """Structural transition accepted by the shared durable outbox."""

    @property
    def kind(self) -> str:
        """Return the monitoring event kind."""
        raise NotImplementedError

    @property
    def occurred_at(self) -> float:
        """Return the source transition timestamp."""
        raise NotImplementedError

    @property
    def details(self) -> JsonObject:
        """Return the complete immutable event details."""
        raise NotImplementedError


LOGGER = logging.getLogger(__name__)

_MAX_BATCH = 100
_MAX_BACKOFF_SECONDS = 300.0
_MAX_BACKOFF_EXPONENT = 8


@dataclass
class DatabaseEventBus:
    """One persisted Events Bus producer queue for database transitions."""

    config: EventBusConfig
    entries: list[JsonObject]

    @classmethod
    def from_state(cls, state: JsonObject) -> DatabaseEventBus | None:
        """Load optional delivery configuration and retained entries.

        Returns:
            A configured producer, or ``None`` when delivery is unconfigured.

        Raises:
            TypeError: If the persisted outbox shape is invalid.
        """
        config = EVENT_BUS_RUNTIME.load_event_bus_config()
        if config is None:
            return None
        raw_entries = state.get("event_bus_outbox", [])
        entries = object_list(raw_entries)
        if not isinstance(raw_entries, list) or len(entries) != len(raw_entries):
            message = "persisted database Events Bus outbox must contain only objects"
            raise TypeError(message)
        return cls(config=config, entries=[_validated_entry(entry) for entry in entries])

    @property
    def pending_count(self) -> int:
        """Return the number of retained deliveries."""
        return len(self.entries)

    def staged_for_cycle(
        self,
        *,
        previous: JsonObject,
        updated: JsonObject,
    ) -> DatabaseEventBus:
        """Clone the retained queue and append this cycle's transitions.

        Returns:
            A staged producer to checkpoint atomically with collector state.

        Raises:
            RuntimeError: If the database transition builder violates its scope.
        """
        transitions = database_transition_events(previous=previous, updated=updated)
        if any(not event.kind.startswith("database_") for event in transitions):
            message = "database transition builder returned an unrelated event"
            raise RuntimeError(message)
        return self.staged_events(transitions)

    def staged_events(
        self,
        events: Sequence[IncidentEvent],
    ) -> DatabaseEventBus:
        """Clone the retained queue and append immutable incident transitions.

        Returns:
            A staged producer suitable for an atomic state checkpoint.
        """
        copied_entries = object_list(normalize_json(cast("JsonInput", self.entries)))
        staged = DatabaseEventBus(config=self.config, entries=copied_entries)
        known_delivery_ids = {
            text_value(optional_object(entry.get("payload")).get("delivery_id")) for entry in staged.entries
        }
        for event in events:
            payload = DELIVERY_RUNTIME.build_incident_payload(
                self.config,
                kind=event.kind,
                occurred_at=event.occurred_at,
                details=event.details,
            )
            delivery_id = text_value(payload.get("delivery_id"))
            if delivery_id in known_delivery_ids:
                continue
            staged.entries.append(
                json_object(
                    {
                        "payload": normalize_json(cast("JsonInput", payload)),
                        "attempts": 0,
                        "next_attempt_at": 0.0,
                        "last_error": None,
                    },
                ),
            )
            known_delivery_ids.add(delivery_id)
        return staged

    def state_value(self) -> JsonValue:
        """Return a strict JSON snapshot suitable for collector state."""
        return normalize_json(cast("JsonInput", self.entries))

    def flush(
        self,
        *,
        now: float | None = None,
        transport: BaseTransport | None = None,
    ) -> tuple[DeliveryAttempt, ...]:
        """Attempt a bounded due batch and retain failures for retry.

        Returns:
            Completed delivery receipts in attempted order.
        """
        selected_now = time.time() if now is None else now
        attempts: list[DeliveryAttempt] = []
        for entry in list(self.entries)[:_MAX_BATCH]:
            due_at = float_value(entry.get("next_attempt_at"))
            if due_at is None or due_at > selected_now:
                break
            payload = optional_object(entry.get("payload"))
            attempt = DELIVERY_RUNTIME.deliver_event_bus_payload(
                self.config,
                payload,
                now=selected_now,
                transport=transport,
            )
            attempts.append(attempt)
            if attempt.success:
                self.entries.remove(entry)
            else:
                _record_failure(entry, attempt=attempt, now=selected_now)
            LOGGER.info(
                "database Events Bus delivery success=%s delivery_id=%s status=%s event_id=%s error=%s pending=%s",
                attempt.success,
                attempt.delivery_id,
                attempt.status_code,
                attempt.event_id,
                attempt.error,
                self.pending_count,
            )
            if not attempt.success:
                break
        return tuple(attempts)


def _validated_entry(entry: JsonObject) -> JsonObject:
    payload = optional_object(entry.get("payload"))
    attempts = int_value(entry.get("attempts"))
    next_attempt_at = float_value(entry.get("next_attempt_at"))
    last_error = entry.get("last_error")
    delivery_id = text_value(payload.get("delivery_id"))
    if not delivery_id.startswith("monitoring-"):
        message = "persisted database Events Bus delivery id is invalid"
        raise TypeError(message)
    if attempts is None or attempts < 0 or next_attempt_at is None:
        message = "persisted database Events Bus retry metadata is invalid"
        raise TypeError(message)
    if last_error is not None and not isinstance(last_error, str):
        message = "persisted database Events Bus last error is invalid"
        raise TypeError(message)
    return json_object(
        {
            "payload": payload,
            "attempts": attempts,
            "next_attempt_at": next_attempt_at,
            "last_error": last_error,
        },
    )


def _record_failure(entry: JsonObject, *, attempt: DeliveryAttempt, now: float) -> None:
    prior_attempts = int_value(entry.get("attempts")) or 0
    attempt_count = prior_attempts + 1
    entry["attempts"] = attempt_count
    entry["last_error"] = attempt.error or "unknown_delivery_error"
    exponent = min(attempt_count, _MAX_BACKOFF_EXPONENT)
    entry["next_attempt_at"] = now + min(_MAX_BACKOFF_SECONDS, 2.0**exponent)
