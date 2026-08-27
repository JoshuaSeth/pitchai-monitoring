# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared synchronous delivery gateway for immutable monitoring envelopes."""

from __future__ import annotations

import hashlib
import json
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, cast

from httpx import Client

from .event_bus import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    DeliveryAttempt,
    signature_for_delivery,
)

if TYPE_CHECKING:
    from httpx import BaseTransport, Response

    from .event_bus import EventBusConfig

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

_ACCEPTED_STATUS = 202
_DELIVERY_PREFIX = "monitoring-"
_EVENT_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_USER_AGENT = "PitchAI Monitoring Events Bus"


def build_incident_payload(
    config: EventBusConfig,
    *,
    kind: str,
    occurred_at: float,
    details: JsonObject,
) -> JsonObject:
    """Build one immutable incident envelope with a stable delivery identity.

    Returns:
        A strict JSON payload ready for durable producer storage.

    Raises:
        ValueError: If the event kind or payload identity is invalid.
    """
    if _EVENT_KIND_PATTERN.fullmatch(kind) is None:
        message = f"invalid monitoring event kind: {kind}"
        raise ValueError(message)
    source: JsonObject = {
        "service": "service-monitoring",
        "environment": config.environment,
        "instance": config.instance,
    }
    if config.deployment_sha is not None:
        source["deployment_sha"] = config.deployment_sha
    payload: JsonObject = {
        "schema_version": 1,
        "event_kind": kind,
        "occurred_at": datetime.fromtimestamp(occurred_at, tz=UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "source": source,
        "details": deepcopy(details),
    }
    identity = hashlib.sha256(_canonical_json(payload)).hexdigest()
    payload["delivery_id"] = f"{_DELIVERY_PREFIX}{identity}"
    _validate_payload(payload)
    return payload


def deliver_event_bus_payload(
    config: EventBusConfig,
    immutable_payload: JsonObject,
    *,
    now: float | None = None,
    transport: BaseTransport | None = None,
) -> DeliveryAttempt:
    """Deliver one already-built envelope through the approved HTTP boundary.

    The gateway copies and validates the envelope before signing its canonical
    bytes. The stable producer delivery id remains the receiver dedupe key.

    Returns:
        The existing monitoring delivery receipt for a completed HTTP exchange.

    Invalid envelopes and transport/protocol errors fail loudly so the owning
    durable outbox retains the source row for retry.
    """
    payload = deepcopy(immutable_payload)
    delivery_id, event_kind = _validate_payload(payload)
    body = _canonical_json(payload)
    timestamp = str(int(time.time() if now is None else now))
    signature = signature_for_delivery(
        body=body,
        secret=config.secret,
        timestamp=timestamp,
        delivery_id=delivery_id,
        event_kind=event_kind,
    )
    headers = {"content-type": "application/json", SIGNATURE_HEADER: signature}
    headers[DELIVERY_HEADER] = delivery_id
    headers[TIMESTAMP_HEADER] = timestamp
    headers[EVENT_HEADER] = event_kind
    client_factory = partial(
        Client,
        headers={"User-Agent": _USER_AGENT},
        transport=transport,
        trust_env=False,
    )
    with client_factory() as client:
        response = client.post(
            config.webhook_url,
            content=body,
            headers=headers,
            timeout=config.timeout_seconds,
        )
    return _delivery_attempt(delivery_id=delivery_id, response=response)


def _validate_payload(payload: JsonObject) -> tuple[str, str]:
    delivery_id = payload.get("delivery_id")
    event_kind = payload.get("event_kind")
    if payload.get("schema_version") != 1:
        message = "monitoring event schema version must be 1"
        raise TypeError(message)
    if not isinstance(event_kind, str) or _EVENT_KIND_PATTERN.fullmatch(event_kind) is None:
        message = "monitoring event kind is invalid"
        raise ValueError(message)
    if not isinstance(payload.get("source"), dict) or not isinstance(payload.get("details"), dict):
        message = "monitoring event source and details must be objects"
        raise TypeError(message)
    if not isinstance(delivery_id, str) or not delivery_id.startswith(_DELIVERY_PREFIX):
        message = "monitoring event delivery id is invalid"
        raise ValueError(message)
    identity_payload = dict(payload)
    identity_payload.pop("delivery_id")
    expected = f"{_DELIVERY_PREFIX}{hashlib.sha256(_canonical_json(identity_payload)).hexdigest()}"
    if delivery_id != expected:
        message = "monitoring event delivery identity does not match its immutable payload"
        raise ValueError(message)
    return delivery_id, event_kind


def _canonical_json(payload: JsonObject) -> bytes:
    encoder = json.JSONEncoder(
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return encoder.encode(payload).encode()


def _delivery_attempt(*, delivery_id: str, response: Response) -> DeliveryAttempt:
    if response.status_code != _ACCEPTED_STATUS:
        return _failed_attempt(
            delivery_id=delivery_id,
            status_code=response.status_code,
            error=f"http_status_{response.status_code}",
        )
    decoded = cast("object", json.loads(response.text))
    if not isinstance(decoded, dict):
        return _invalid_acceptance(delivery_id=delivery_id, status_code=response.status_code)
    response_object = cast("dict[object, object]", decoded)
    event_ids = response_object.get("event_ids")
    if response_object.get("accepted") != 1 or not isinstance(event_ids, list):
        return _invalid_acceptance(delivery_id=delivery_id, status_code=response.status_code)
    typed_event_ids = cast("list[object]", event_ids)
    if len(typed_event_ids) != 1:
        return _invalid_acceptance(delivery_id=delivery_id, status_code=response.status_code)
    event_id = typed_event_ids[0]
    if not isinstance(event_id, str) or not event_id:
        return _invalid_acceptance(delivery_id=delivery_id, status_code=response.status_code)
    return DeliveryAttempt(
        delivery_id=delivery_id,
        success=True,
        status_code=response.status_code,
        event_id=event_id,
        error=None,
    )


def _invalid_acceptance(*, delivery_id: str, status_code: int) -> DeliveryAttempt:
    return _failed_attempt(
        delivery_id=delivery_id,
        status_code=status_code,
        error="invalid_acceptance_response",
    )


def _failed_attempt(*, delivery_id: str, status_code: int, error: str) -> DeliveryAttempt:
    return DeliveryAttempt(
        delivery_id=delivery_id,
        success=False,
        status_code=status_code,
        event_id=None,
        error=error,
    )
