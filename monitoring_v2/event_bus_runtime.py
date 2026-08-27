# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed boundary to the shared monitoring Events Bus producer package."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from .json_types import JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from httpx import BaseTransport

type DeliveryPayload = dict[str, JsonValue]


@dataclass(frozen=True)
class EventBusConfig:
    """Typed structural view of the shared monitoring producer configuration."""

    webhook_url: str
    secret: str
    environment: str
    instance: str
    deployment_sha: str | None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class DeliveryAttempt:
    """Typed structural view of a shared monitoring delivery receipt."""

    delivery_id: str
    success: bool
    status_code: int | None
    event_id: str | None
    error: str | None


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
