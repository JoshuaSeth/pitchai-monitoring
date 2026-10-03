# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retain CPU baselines and the original dashboard snapshot between cycles."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .cycle_values import required_int

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


@dataclass
class HostObservations:
    """The existing host-specific state, separate from its health debounce."""

    cpu_prev_total: int = 0
    cpu_prev_idle: int = 0
    last_snapshot: JsonObject = field(default_factory=dict)

    def advance_cpu(self, snapshot: JsonObject) -> None:
        """Retain missing baselines and the original sequential conversion order."""
        total = snapshot.get("cpu_prev_total_next")
        idle = snapshot.get("cpu_prev_idle_next")
        if total is not None and idle is not None:
            with suppress(TypeError, ValueError, OverflowError):
                self.cpu_prev_total = required_int(total)
                self.cpu_prev_idle = required_int(idle)

    def capture(self, snapshot: JsonObject) -> None:
        """Keep the same shallow dashboard copy without private CPU-next fields."""
        self.last_snapshot = dict(snapshot)
        self.last_snapshot.pop("cpu_prev_total_next", None)
        self.last_snapshot.pop("cpu_prev_idle_next", None)
