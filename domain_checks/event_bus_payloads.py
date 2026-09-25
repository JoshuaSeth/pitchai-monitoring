# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict payload identity and persistence validation for monitoring events."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from domain_checks.event_bus_models import (
    DELIVERY_PREFIX,
    MONITORING_EVENT_KINDS,
    SIGNATURE_VERSION,
    EventIdentityPayload,
    EventPayload,
    EventSource,
    OutboxEntry,
)

if TYPE_CHECKING:
    from domain_checks.event_bus_models import EventBusConfig, EventOutboxInput
    from domain_checks.types import JsonObject, JsonValue


def canonical_json(payload: EventIdentityPayload | EventPayload | JsonObject) -> bytes:
    """Encode a payload as strict deterministic JSON.

    Returns:
        The canonical UTF-8 JSON bytes.

    Raises:
        ValueError: The payload cannot be represented as strict JSON.
    """
    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        message = "PitchAI monitoring event payload is not strict JSON"
        raise ValueError(message) from exc


def build_payload(
    config: EventBusConfig,
    *,
    kind: str,
    occurred_at: float,
    details: JsonObject,
) -> EventPayload:
    """Build one deterministic strict monitoring-event envelope.

    Returns:
        The validated event envelope.

    Raises:
        ValueError: The event kind or payload is invalid.
    """
    if kind not in MONITORING_EVENT_KINDS:
        message = f"Unsupported PitchAI monitoring event kind: {kind}"
        raise ValueError(message)
    source = EventSource(
        service="service-monitoring",
        environment=config.environment,
        instance=config.instance,
    )
    if config.deployment_sha:
        source["deployment_sha"] = config.deployment_sha
    identity = EventIdentityPayload(
        schema_version=1,
        event_kind=kind,
        occurred_at=_iso_timestamp(occurred_at),
        source=source,
        details=copy.deepcopy(details),
    )
    delivery_id = f"{DELIVERY_PREFIX}{hashlib.sha256(canonical_json(identity)).hexdigest()}"
    payload = EventPayload(**identity, delivery_id=delivery_id)
    _ = canonical_json(payload)
    return payload


def signature_for_delivery(
    *,
    body: bytes,
    secret: str,
    timestamp: str,
    delivery_id: str,
    event_kind: str,
) -> str:
    """Sign timestamp, identity, event kind, and body as one envelope.

    Returns:
        The hexadecimal SHA-256 signature header value.
    """
    signed = f"{SIGNATURE_VERSION}\n{timestamp}\n{delivery_id}\n{event_kind}\n".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def validated_entry(raw_entry: EventOutboxInput) -> OutboxEntry:
    """Validate a persisted outbox record, including its derived identity.

    Returns:
        A validated mutable outbox entry.

    Raises:
        TypeError: The persisted entry does not contain a payload mapping.
    """
    payload_value = raw_entry.get("payload")
    if not isinstance(payload_value, dict):
        message = "PitchAI monitoring Events Bus outbox payload is missing"
        raise TypeError(message)
    payload = _validated_payload(cast("JsonObject", payload_value))
    attempts, next_attempt_at, last_error = _validated_retry_state(raw_entry)
    return OutboxEntry(
        payload=payload,
        attempts=attempts,
        next_attempt_at=next_attempt_at,
        last_error=last_error,
    )


def _validated_payload(payload: JsonObject) -> EventPayload:
    delivery_id = payload.get("delivery_id")
    event_kind = payload.get("event_kind")
    if not isinstance(delivery_id, str) or not delivery_id.startswith(DELIVERY_PREFIX):
        message = "PitchAI monitoring Events Bus outbox delivery id is invalid"
        raise RuntimeError(message)
    if not isinstance(event_kind, str) or event_kind not in MONITORING_EVENT_KINDS:
        message = "PitchAI monitoring Events Bus outbox event kind is invalid"
        raise RuntimeError(message)
    occurred_at = _validated_metadata(payload)
    source = _validated_source(payload.get("source"))
    details = payload.get("details")
    if not isinstance(details, dict):
        message = "PitchAI monitoring Events Bus outbox payload content is invalid"
        raise TypeError(message)
    identity = EventIdentityPayload(
        schema_version=1,
        event_kind=event_kind,
        occurred_at=occurred_at,
        source=source,
        details=copy.deepcopy(details),
    )
    expected = f"{DELIVERY_PREFIX}{hashlib.sha256(canonical_json(identity)).hexdigest()}"
    if delivery_id != expected:
        message = "PitchAI monitoring Events Bus outbox delivery identity is invalid"
        raise RuntimeError(message)
    validated = EventPayload(**identity, delivery_id=delivery_id)
    _ = canonical_json(validated)
    return validated


def _validated_metadata(payload: JsonObject) -> str:
    occurred_at = payload.get("occurred_at")
    if payload.get("schema_version") != 1 or not isinstance(occurred_at, str):
        message = "PitchAI monitoring Events Bus outbox payload metadata is invalid"
        raise RuntimeError(message)
    return occurred_at


def _validated_source(value: JsonValue) -> EventSource:
    if not isinstance(value, dict):
        message = "PitchAI monitoring Events Bus outbox payload content is invalid"
        raise TypeError(message)
    service = value.get("service")
    environment = value.get("environment")
    instance = value.get("instance")
    if not isinstance(service, str) or not service:
        message = "PitchAI monitoring Events Bus outbox source is invalid"
        raise RuntimeError(message)
    if not isinstance(environment, str) or not environment:
        message = "PitchAI monitoring Events Bus outbox source is invalid"
        raise RuntimeError(message)
    if not isinstance(instance, str) or not instance:
        message = "PitchAI monitoring Events Bus outbox source is invalid"
        raise RuntimeError(message)
    source = EventSource(service=service, environment=environment, instance=instance)
    deployment_sha = value.get("deployment_sha")
    if deployment_sha is not None:
        if not isinstance(deployment_sha, str):
            message = "PitchAI monitoring Events Bus outbox deployment SHA is invalid"
            raise TypeError(message)
        source["deployment_sha"] = deployment_sha
    return source


def _validated_retry_state(
    raw_entry: EventOutboxInput,
) -> tuple[int, float, str | None]:
    attempts = raw_entry.get("attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
        message = "PitchAI monitoring Events Bus outbox attempt count is invalid"
        raise RuntimeError(message)
    next_attempt_at = raw_entry.get("next_attempt_at")
    if not isinstance(next_attempt_at, (int, float)) or isinstance(
        next_attempt_at,
        bool,
    ):
        message = "PitchAI monitoring Events Bus retry timestamp is invalid"
        raise TypeError(message)
    last_error = raw_entry.get("last_error")
    if last_error is not None and not isinstance(last_error, str):
        message = "PitchAI monitoring Events Bus last error is invalid"
        raise RuntimeError(message)
    return attempts, float(next_attempt_at), last_error


def _iso_timestamp(value: float) -> str:
    return (
        datetime
        .fromtimestamp(float(value), tz=UTC)
        .isoformat(
            timespec="microseconds",
        )
        .replace("+00:00", "Z")
    )
