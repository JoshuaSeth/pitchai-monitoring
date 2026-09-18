# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for the hotpath Events Bus adapter."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from httpx import BaseTransport


class HotpathEventBusConfig(NamedTuple):
    """Structural view of the hotpath Events Bus configuration."""

    timeout_seconds: float
    deployment_sha: str
    instance: str
    environment: str
    secret: str
    webhook_url: str


class HotpathEventWork(NamedTuple):
    """Structural view of one leased hotpath incident intent."""

    payload_json: str
    delivery_id: str
    event_kind: str
    intent_id: str


class HotpathGatewayResult(Protocol):
    """Secret-free outcome returned by the hotpath gateway."""

    @property
    def event_id(self) -> str | None:
        """Return the receiver event id when accepted."""
        raise NotImplementedError

    @property
    def error(self) -> str | None:
        """Return a stable delivery error when rejected."""
        raise NotImplementedError


class _HotpathEventGatewayModule(Protocol):
    async def deliver_event(
        self,
        config: HotpathEventBusConfig,
        work: HotpathEventWork,
        *,
        now_ts: float,
        transport: BaseTransport | None = None,
    ) -> HotpathGatewayResult:
        """Deliver one persisted hotpath event through the shared gateway."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


HOTPATH_EVENT_GATEWAY = cast(
    "_HotpathEventGatewayModule",
    cast("object", import_module("e2e_registry.hotpath_event_gateway")),
)
