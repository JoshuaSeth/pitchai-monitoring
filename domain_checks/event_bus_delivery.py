# Copyright (c) 2026 PitchAI. All rights reserved.
"""At-least-once Events Bus delivery queue and HTTP boundary."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, cast, final

import httpx

from domain_checks.event_bus_models import (
    ACCEPTED_STATUS_CODE,
    DELIVERY_HEADER,
    EVENT_HEADER,
    MAX_FLUSH_BATCH,
    MAX_PENDING_DELIVERIES,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    DeliveryAttempt,
    OutboxEntry,
)
from domain_checks.event_bus_payloads import (
    build_payload,
    canonical_json,
    signature_for_delivery,
    validated_entry,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from domain_checks.event_bus_models import (
        EventBusConfig,
        EventOutboxInput,
        EventOutboxState,
    )
    from domain_checks.types import JsonObject, JsonValue


@final
class EventBusOutbox:
    """Persisted at-least-once queue with receiver-side dedupe identity."""

    def __init__(
        self,
        config: EventBusConfig,
        entries: Sequence[EventOutboxInput] | None = None,
    ) -> None:
        """Load and validate persisted pending deliveries.

        Raises:
            RuntimeError: The restored outbox exceeds its safety limit.
        """
        self.config = config
        source_entries = entries or []
        self._entries = [validated_entry(entry) for entry in source_entries]
        if len(self._entries) > MAX_PENDING_DELIVERIES:
            message = "PitchAI monitoring Events Bus outbox exceeds its safety limit"
            raise RuntimeError(message)

    @property
    def pending_count(self) -> int:
        """Return the number of pending deliveries."""
        return len(self._entries)

    def enqueue(self, kind: str, *, occurred_at: float, details: JsonObject) -> str:
        """Append one event unless its stable delivery identity is already queued.

        Returns:
            The event's stable delivery identifier.

        Raises:
            RuntimeError: The outbox has reached its safety limit.
        """
        if len(self._entries) >= MAX_PENDING_DELIVERIES:
            message = "PitchAI monitoring Events Bus outbox is full"
            raise RuntimeError(message)
        payload = build_payload(
            self.config,
            kind=kind,
            occurred_at=occurred_at,
            details=details,
        )
        delivery_id = payload["delivery_id"]
        if any(entry.delivery_id == delivery_id for entry in self._entries):
            return delivery_id
        self._entries.append(
            OutboxEntry(
                payload=payload,
                attempts=0,
                next_attempt_at=0.0,
                last_error=None,
            ),
        )
        return delivery_id

    def to_state(self) -> list[EventOutboxState]:
        """Return isolated persistence records for every pending delivery."""
        return [entry.to_state() for entry in self._entries]

    async def flush(
        self,
        client: httpx.AsyncClient,
        *,
        now: float | None = None,
        max_deliveries: int = MAX_FLUSH_BATCH,
    ) -> list[DeliveryAttempt]:
        """Deliver eligible entries in order, stopping after the first failure.

        Returns:
            Delivery results in queue order.
        """
        selected_now = time.time() if now is None else float(now)
        attempts: list[DeliveryAttempt] = []
        for entry in list(self._entries)[: max(1, int(max_deliveries))]:
            if entry.next_attempt_at > selected_now:
                break
            attempt = await _deliver_entry(client, self.config, entry, now=selected_now)
            attempts.append(attempt)
            if attempt.success:
                self._entries.remove(entry)
                continue
            _record_failure(entry, attempt, now=selected_now)
            break
        return attempts


async def _deliver_entry(
    client: httpx.AsyncClient,
    config: EventBusConfig,
    entry: OutboxEntry,
    *,
    now: float,
) -> DeliveryAttempt:
    body = canonical_json(entry.payload)
    timestamp = str(int(now))
    event_kind = entry.payload["event_kind"]
    headers = {
        "content-type": "application/json",
        SIGNATURE_HEADER: signature_for_delivery(
            body=body,
            secret=config.secret,
            timestamp=timestamp,
            delivery_id=entry.delivery_id,
            event_kind=event_kind,
        ),
        DELIVERY_HEADER: entry.delivery_id,
        TIMESTAMP_HEADER: timestamp,
        EVENT_HEADER: event_kind,
    }
    try:
        response = await client.post(
            config.webhook_url,
            content=body,
            headers=headers,
            timeout=config.timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return DeliveryAttempt(
            delivery_id=entry.delivery_id,
            success=False,
            status_code=None,
            event_id=None,
            error=type(exc).__name__,
        )
    return _response_attempt(response, entry.delivery_id)


def _response_attempt(response: httpx.Response, delivery_id: str) -> DeliveryAttempt:
    if response.status_code != ACCEPTED_STATUS_CODE:
        return DeliveryAttempt(
            delivery_id=delivery_id,
            success=False,
            status_code=response.status_code,
            event_id=None,
            error=f"http_status_{response.status_code}",
        )
    event_id = _accepted_event_id(response)
    return DeliveryAttempt(
        delivery_id=delivery_id,
        success=event_id is not None,
        status_code=response.status_code,
        event_id=event_id,
        error=None if event_id is not None else "invalid_acceptance_response",
    )


def _accepted_event_id(response: httpx.Response) -> str | None:
    try:
        payload = cast("JsonValue", response.json())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("accepted") != 1:
        return None
    event_ids = payload.get("event_ids")
    if not isinstance(event_ids, list) or len(event_ids) != 1:
        return None
    event_id = event_ids[0]
    return event_id if isinstance(event_id, str) and event_id else None


def _record_failure(
    entry: OutboxEntry,
    attempt: DeliveryAttempt,
    *,
    now: float,
) -> None:
    entry.attempts += 1
    entry.last_error = attempt.error or "unknown_delivery_error"
    entry.next_attempt_at = now + min(300.0, 2.0 ** min(entry.attempts, 8))
