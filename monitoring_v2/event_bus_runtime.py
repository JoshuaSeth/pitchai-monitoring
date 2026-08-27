# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed boundary to the shared monitoring Events Bus producer package."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

from .json_types import JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from httpx import BaseTransport

type DeliveryPayload = dict[str, JsonValue]


class EventBusConfig(NamedTuple):
    """Structural view of the shared producer configuration."""

    instance: str
    environment: str
    webhook_url: str
    deployment_sha: str | None
    secret: str
    timeout_seconds: float = 10.0


class DeliveryAttempt(NamedTuple):
    """Structural view of one shared delivery receipt."""

    error: str | None
    event_id: str | None
    status_code: int | None
    success: bool
    delivery_id: str


type EventBusConfigClass = type[EventBusConfig]
type EventBusConfigValue = EventBusConfig


class _EventBusRuntime(Protocol):
    EventBusConfig: EventBusConfigClass

    def load_event_bus_config(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> EventBusConfigValue | None:
        """Load the shared producer configuration."""
        raise NotImplementedError

    def main(self) -> int:
        """Describe the producer module's command boundary."""
        raise NotImplementedError


class _DeliveryRuntime(Protocol):
    def build_incident_payload(
        self,
        config: EventBusConfig,
        *,
        kind: str,
        occurred_at: float,
        details: DeliveryPayload,
    ) -> DeliveryPayload:
        """Build one shared immutable incident envelope."""
        raise NotImplementedError

    def deliver_event_bus_payload(
        self,
        config: EventBusConfig,
        immutable_payload: DeliveryPayload,
        *,
        now: float | None = None,
        transport: BaseTransport | None = None,
    ) -> DeliveryAttempt:
        """Deliver one envelope through the shared producer gateway."""
        raise NotImplementedError


EVENT_BUS_RUNTIME = cast(
    "_EventBusRuntime",
    cast("object", import_module("domain_checks.event_bus")),
)
DELIVERY_RUNTIME = cast(
    "_DeliveryRuntime",
    cast("object", import_module("domain_checks.event_bus_delivery")),
)
