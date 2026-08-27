# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed boundary to the shared monitoring Events Bus producer package."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from .json_types import JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from httpx import BaseTransport

type DeliveryPayload = dict[str, JsonValue]


class EventBusConfig(Protocol):
    """Typed structural view of the shared monitoring producer configuration."""

    @property
    def webhook_url(self) -> str:
        """Return the configured receiver URL."""
        raise NotImplementedError

    @property
    def secret(self) -> str:
        """Return the shared signing secret."""
        raise NotImplementedError

    @property
    def environment(self) -> str:
        """Return the producer environment."""
        raise NotImplementedError

    @property
    def instance(self) -> str:
        """Return the producer instance."""
        raise NotImplementedError

    @property
    def deployment_sha(self) -> str | None:
        """Return the optional deployed source revision."""
        raise NotImplementedError

    @property
    def timeout_seconds(self) -> float:
        """Return the delivery timeout."""
        raise NotImplementedError


class DeliveryAttempt(Protocol):
    """Typed structural view of a shared monitoring delivery receipt."""

    @property
    def delivery_id(self) -> str:
        """Return the stable delivery identity."""
        raise NotImplementedError

    @property
    def success(self) -> bool:
        """Return whether the receiver accepted the event."""
        raise NotImplementedError

    @property
    def status_code(self) -> int | None:
        """Return the HTTP status when an exchange completed."""
        raise NotImplementedError

    @property
    def event_id(self) -> str | None:
        """Return the receiver event identity when accepted."""
        raise NotImplementedError

    @property
    def error(self) -> str | None:
        """Return a stable failure description."""
        raise NotImplementedError


class _EventBusRuntime(Protocol):
    def load_event_bus_config(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> EventBusConfig | None:
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
