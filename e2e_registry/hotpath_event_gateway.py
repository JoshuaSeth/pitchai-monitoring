# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit shared-gateway adapter for hotpath Events Bus delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

from .hotpath_codec import decode_object

if TYPE_CHECKING:
    from collections.abc import Mapping

    from httpx import BaseTransport

    from .hotpath_event_bus_runtime import EventBusConfig
    from .hotpath_types import JsonValue


class DeliveryAttempt(NamedTuple):
    """Secret-free receipt returned by the established shared gateway."""

    delivery_id: str
    success: bool
    status_code: int | None
    event_id: str | None
    error: str | None


class DeliveryGateway(Protocol):
    """Established synchronous producer boundary owned by the Events Bus."""

    def __call__(
        self,
        config: EventBusConfig,
        payload: Mapping[str, JsonValue],
        *,
        now: float | None = None,
        transport: BaseTransport | None = None,
    ) -> DeliveryAttempt:
        """Deliver one immutable event envelope and return its receipt."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


@dataclass(frozen=True)
class EventWork:
    """One leased intent and its immutable signed-delivery payload."""

    intent_id: str
    event_kind: str
    delivery_id: str
    payload_json: str


@dataclass(frozen=True)
class GatewayResult:
    """Secret-free outcome returned by the Events Bus gateway."""

    event_id: str | None
    error: str | None


async def deliver_event(
    config: EventBusConfig,
    work: EventWork,
    *,
    now_ts: float,
    transport: BaseTransport | None = None,
) -> GatewayResult:
    """Deliver a persisted payload through the canonical shared gateway.

    Returns:
        A secret-free delivery outcome suitable for durable retry state.
    """
    gateway = _delivery_gateway()
    if gateway is None:
        return GatewayResult(event_id=None, error="shared_gateway_unavailable")
    payload = decode_object(work.payload_json)
    attempt = await asyncio.to_thread(
        gateway,
        config,
        payload,
        now=now_ts,
        transport=transport,
    )
    if attempt.delivery_id != work.delivery_id:
        return GatewayResult(event_id=None, error="shared_gateway_delivery_id_mismatch")
    if attempt.success and attempt.event_id:
        return GatewayResult(event_id=attempt.event_id, error=None)
    status = f":http_{attempt.status_code}" if attempt.status_code is not None else ""
    return GatewayResult(event_id=None, error=f"{attempt.error or 'delivery_failed'}{status}")


def _delivery_gateway() -> DeliveryGateway | None:
    module = import_module("domain_checks.event_bus_delivery")
    candidate = getattr(module, "deliver_event_bus_payload", None)
    return cast("DeliveryGateway", candidate) if callable(candidate) else None
