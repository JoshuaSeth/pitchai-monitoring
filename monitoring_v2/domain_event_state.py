# Copyright (c) 2026 PitchAI. All rights reserved.
"""Durable state contract for production domain incident delivery."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, cast

from .domain_event_models import DomainIncidentReceipt, DomainProducerState
from .json_types import (
    bool_value,
    float_value,
    json_object,
    normalize_json,
    object_list,
    optional_object,
    text_value,
    value_list,
)
from .state_io import load_state

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonInput, JsonObject, JsonValue

STATE_VERSION = 1
MAX_SEEN_EVENTS = 4_000
_EVENT_ID_LENGTH = 64


def empty_domain_producer_state() -> DomainProducerState:
    """Return a strict first-run producer state."""
    return DomainProducerState(
        bootstrapped=False,
        seen_event_ids=(),
        incidents={},
        outbox=[],
        updated_at_ts=0.0,
        last_error=None,
        last_delivery_id=None,
        last_receiver_event_id=None,
        last_delivered_at_ts=None,
    )


def load_domain_producer_state(path: Path) -> DomainProducerState:
    """Load and validate retained domain producer state.

    Returns:
        A validated state, or the explicit first-run state when absent.

    Raises:
        ValueError: If the retained state contract is invalid.
    """
    if not path.exists():
        return empty_domain_producer_state()
    state = load_state(path)
    if state.get("version") != STATE_VERSION:
        message = "domain incident producer state version is unsupported"
        raise ValueError(message)
    producer = optional_object(state.get("producer"))
    bootstrapped = bool_value(producer.get("bootstrapped"))
    updated_at = float_value(producer.get("updated_at_ts"))
    if bootstrapped is None or updated_at is None:
        message = "domain incident producer metadata is invalid"
        raise ValueError(message)
    return DomainProducerState(
        bootstrapped=bootstrapped,
        seen_event_ids=_seen_event_ids(state),
        incidents=_incidents(state),
        outbox=object_list(state.get("event_bus_outbox")),
        updated_at_ts=updated_at,
        last_error=_optional_text(producer.get("last_error")),
        last_delivery_id=_optional_text(producer.get("last_delivery_id")),
        last_receiver_event_id=_optional_text(producer.get("last_receiver_event_id")),
        last_delivered_at_ts=float_value(producer.get("last_delivered_at_ts")),
    )


def domain_producer_state_value(state: DomainProducerState) -> JsonObject:
    """Return a compact, operator-inspectable JSON checkpoint."""
    incidents: JsonObject = {}
    for domain, receipt in sorted(state.incidents.items()):
        incidents[domain] = {
            "incident_fingerprint": receipt.fingerprint,
            "last_event_at_ts": receipt.last_event_at_ts,
        }
    status = "healthy" if state.last_error is None else "degraded"
    raw_state = {
        "version": STATE_VERSION,
        "producer": {
            "status": status,
            "bootstrapped": state.bootstrapped,
            "updated_at_ts": state.updated_at_ts,
            "pending_count": len(state.outbox),
            "open_incident_count": len(state.incidents),
            "last_error": state.last_error,
            "last_delivery_id": state.last_delivery_id,
            "last_receiver_event_id": state.last_receiver_event_id,
            "last_delivered_at_ts": state.last_delivered_at_ts,
        },
        "seen_event_ids": list(state.seen_event_ids[-MAX_SEEN_EVENTS:]),
        "incidents": incidents,
        "event_bus_outbox": normalize_json(cast("JsonInput", state.outbox)),
    }
    return json_object(cast("JsonInput", raw_state))


def retained_event_id(event: JsonObject) -> str:
    """Return a stable identity for one sanitized retained transition."""
    encoded = json.dumps(event, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seen_event_ids(state: JsonObject) -> tuple[str, ...]:
    raw_identifiers = value_list(state.get("seen_event_ids"))
    identifiers = [item for item in raw_identifiers if isinstance(item, str)]
    if any(len(identifier) != _EVENT_ID_LENGTH for identifier in identifiers):
        message = "domain incident producer retained an invalid event identity"
        raise ValueError(message)
    return tuple(identifiers[-MAX_SEEN_EVENTS:])


def _incidents(state: JsonObject) -> dict[str, DomainIncidentReceipt]:
    incidents: dict[str, DomainIncidentReceipt] = {}
    for domain, raw_receipt in optional_object(state.get("incidents")).items():
        receipt = optional_object(raw_receipt)
        fingerprint = text_value(receipt.get("incident_fingerprint"))
        last_event_at = float_value(receipt.get("last_event_at_ts"))
        if not fingerprint.startswith("sha256:") or last_event_at is None:
            message = f"domain incident producer receipt is invalid: {domain}"
            raise ValueError(message)
        incidents[domain] = DomainIncidentReceipt(fingerprint, last_event_at)
    return incidents


def _optional_text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None
