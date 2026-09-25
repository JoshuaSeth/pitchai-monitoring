# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define service source contracts and mutable runtime state."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from .json_contract import JsonObject
    from .models import DashboardSnapshot


class StateSource(Protocol):
    """Declare the broker state operations used by the dashboard service."""

    def read_accounts(self) -> list[JsonObject]:
        """Read the current broker account state."""
        raise NotImplementedError

    def probe_accounts(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Probe safe account state for the supplied accounts."""
        raise NotImplementedError

    def probe_analytics(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Probe analytics for the supplied accounts."""
        raise NotImplementedError

    def close(self) -> None:
        """Close source resources."""
        raise NotImplementedError


@dataclass
class ProbeState:
    """Track one probe class's cadence, timestamp, and boundary errors."""

    last_monotonic: float | None = None
    last_at: datetime | None = None
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class ServiceRuntime:
    """Group mutable service state behind a bounded instance surface."""

    snapshot: DashboardSnapshot | None = None
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    loop_task: asyncio.Task[None] | None = None
    safe_probe: ProbeState = field(default_factory=ProbeState)
    analytics_probe: ProbeState = field(default_factory=ProbeState)


def probe_due(state: ProbeState, *, interval_seconds: int) -> bool:
    """Return whether one monotonic probe interval has elapsed."""
    if state.last_monotonic is None:
        return True
    return time.monotonic() - state.last_monotonic >= interval_seconds
