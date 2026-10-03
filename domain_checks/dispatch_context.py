# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed arguments for the existing monitoring dispatch lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, TypedDict

from .dispatch_records import DispatchRecords

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .dispatch_client import DispatchConfig
    from .event_bus_delivery import JsonObject
    from .telegram import TelegramConfig


class DispatchInputs(TypedDict):
    """Existing shared keyword fields, including optional collection references."""

    http_client: AsyncClient
    telegram_cfg: TelegramConfig
    dispatch_cfg: DispatchConfig
    dispatch_state: JsonObject
    dispatch_history: NotRequired[list[JsonObject] | None]
    dispatch_last: NotRequired[dict[str, JsonObject] | None]
    events: NotRequired[list[JsonObject] | None]


class PromptInputs(DispatchInputs):
    """Existing prompt dispatch keywords."""

    prompt: str
    state_key: str
    telegram_title: str


@dataclass(frozen=True)
class DispatchRequest:
    """Text and identity of one existing dispatch operation."""

    prompt: str
    state_key: str
    title: str


@dataclass(frozen=True)
class DispatchRuntime:
    """Explicit transport configuration and existing mutable cycle references."""

    client: AsyncClient
    telegram: TelegramConfig
    config: DispatchConfig
    state: JsonObject
    records: DispatchRecords

    @classmethod
    def from_inputs(cls, inputs: DispatchInputs) -> DispatchRuntime:
        """Construct references without copying state or allocating transports.

        Returns:
            The context for the same cycle collections and configured audience.
        """
        records = DispatchRecords(inputs.get("dispatch_history"), inputs.get("dispatch_last"), inputs.get("events"))
        return cls(
            inputs["http_client"], inputs["telegram_cfg"], inputs["dispatch_cfg"], inputs["dispatch_state"], records,
        )


@dataclass(frozen=True)
class DispatchRun:
    """Observed remote run identity, preserving its original start timestamp."""

    started: float
    bundle: str
    runner: str
    queue_state: str
    ui: str

    def entry(self, request: DispatchRequest) -> JsonObject:
        """Return the common existing record fields before outcome fields."""
        return {
            "started_ts": self.started, "state_key": request.state_key, "title": request.title,
            "bundle": self.bundle, "runner": self.runner, "queue_state": self.queue_state, "ui_url": self.ui,
        }
