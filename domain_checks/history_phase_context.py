# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed history phase inputs and the original computation exception boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from .cycle_channels import CycleChannels
    from .event_bus_delivery import JsonObject
    from .history_decode import Sample
    from .signal_history import SignalHistory

LOGGER = logging.getLogger("service-monitoring")


type EventSink = Callable[[str, float, JsonObject], None]


@dataclass(frozen=True)
class HistoryFrame:
    """One phase's current history, original cycle time and existing effects."""

    history: dict[str, list[Sample]]
    alertable: set[str]
    started: float
    channels: CycleChannels
    event: EventSink
    signals: SignalHistory

    def degraded(self, kind: str, domains: list[str]) -> None:
        """Record the same bounded event while preserving full violation count."""
        self.event(kind, float(self.started), {"violations": len(domains), "domains": list(domains[:20])})

    def recovered(self, kind: str) -> None:
        """Record the existing recovery event without choosing or sending a route."""
        self.event(kind, float(self.started), {})


@dataclass(frozen=True)
class HistoryComputeBoundary:
    """Preserve the existing logged-empty fallback for ordinary compute failures."""

    message: str

    def __enter__(self) -> Self:
        """Return this observation boundary without changing health counters."""
        return self

    def __exit__(
        self, _error_type: type[BaseException] | None, error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        """Log ordinary exceptions while leaving cancellation/system exits loud.

        Returns:
            True only for the same exceptions handled by the original phase.
        """
        if not isinstance(error, Exception):
            return False
        LOGGER.error(self.message, exc_info=(type(error), error, _traceback))
        return True
