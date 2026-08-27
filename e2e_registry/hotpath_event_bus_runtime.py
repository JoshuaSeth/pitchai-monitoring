# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for established Events Bus configuration."""

from __future__ import annotations

from importlib import import_module
from typing import NamedTuple, Protocol, cast


class EventBusConfig(NamedTuple):
    """Events Bus configuration fields used by the hotpath producer."""

    webhook_url: str
    secret: str
    environment: str
    instance: str
    deployment_sha: str | None
    timeout_seconds: float


class ConfigLoader(Protocol):
    """Optional established Events Bus configuration loader."""

    def __call__(self) -> EventBusConfig | None:
        """Return configured delivery settings, when enabled."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _EventBusModule(NamedTuple):
    load_event_bus_config: object


_EVENT_BUS = cast(
    "_EventBusModule",
    cast("object", import_module("domain_checks.event_bus")),
)
load_event_bus_config = cast("ConfigLoader", _EVENT_BUS.load_event_bus_config)
