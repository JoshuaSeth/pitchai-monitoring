# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed contracts for durable monitoring event delivery."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    from domain_checks.types import JsonObject

SIGNATURE_HEADER = "X-PitchAI-Monitoring-Signature-256"
DELIVERY_HEADER = "X-PitchAI-Monitoring-Delivery"
TIMESTAMP_HEADER = "X-PitchAI-Monitoring-Timestamp"
EVENT_HEADER = "X-PitchAI-Monitoring-Event"
SIGNATURE_VERSION = "v1"
DELIVERY_PREFIX = "monitoring-"
MAX_PENDING_DELIVERIES = 10_000
MAX_FLUSH_BATCH = 100
ACCEPTED_STATUS_CODE = 202

MONITORING_EVENT_KINDS = frozenset(
    {
        "service_started",
        "integration_test",
        "domain_down",
        "domain_up",
        "slo_degraded",
        "slo_recovered",
        "red_degraded",
        "red_recovered",
        "host_health_degraded",
        "host_health_recovered",
        "performance_degraded",
        "performance_recovered",
        "tls_degraded",
        "tls_recovered",
        "dns_degraded",
        "dns_recovered",
        "api_contract_degraded",
        "api_contract_recovered",
        "container_health_degraded",
        "container_health_recovered",
        "proxy_degraded",
        "proxy_recovered",
        "synthetic_degraded",
        "synthetic_recovered",
        "web_vitals_degraded",
        "web_vitals_recovered",
        "browser_degraded_notice",
        "browser_recovered",
        "meta_degraded",
        "meta_recovered",
    },
)


class EventSource(TypedDict):
    """Identify the monitoring deployment that emitted an event."""

    service: str
    environment: str
    instance: str
    deployment_sha: NotRequired[str]


class EventIdentityPayload(TypedDict):
    """Describe stable fields used to derive an event delivery identity."""

    schema_version: int
    event_kind: str
    occurred_at: str
    source: EventSource
    details: JsonObject


class EventPayload(EventIdentityPayload):
    """Represent one signed monitoring event payload."""

    delivery_id: str


class EventOutboxState(TypedDict):
    """Represent one persisted at-least-once delivery record."""

    payload: EventPayload
    attempts: int
    next_attempt_at: float
    last_error: str | None


type EventOutboxInput = JsonObject | EventOutboxState


@dataclass(frozen=True)
class EventBusConfig:
    """Configure Events Bus delivery and source identity."""

    webhook_url: str
    secret: str
    environment: str
    instance: str
    deployment_sha: str | None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class DeliveryAttempt:
    """Describe one Events Bus delivery attempt."""

    delivery_id: str
    success: bool
    status_code: int | None
    event_id: str | None
    error: str | None


@dataclass
class OutboxEntry:
    """Hold one validated pending Events Bus delivery."""

    payload: EventPayload
    attempts: int
    next_attempt_at: float
    last_error: str | None

    @property
    def delivery_id(self) -> str:
        """Return the stable delivery identity."""
        return self.payload["delivery_id"]

    def to_state(self) -> EventOutboxState:
        """Return an isolated JSON-serializable persistence record."""
        return {
            "payload": copy.deepcopy(self.payload),
            "attempts": self.attempts,
            "next_attempt_at": self.next_attempt_at,
            "last_error": self.last_error,
        }
