# Copyright (c) 2026 PitchAI. All rights reserved.
"""Safe-probe bookkeeping and refresh-loop runtime state of the capacity service."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .capacity import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from .service import StateSource
    from .timeseries_types import JsonObject


@dataclass
class ProbeLedger:
    """When the safe and analytics probes last ran, and the redacted errors they reported."""

    last_probe_monotonic: float | None = None
    last_safe_probe_at: datetime | None = None
    last_probe_errors: dict[str, str] = field(default_factory=dict[str, str])
    last_analytics_probe_monotonic: float | None = None
    last_analytics_probe_at: datetime | None = None
    last_analytics_probe_errors: dict[str, str] = field(default_factory=dict[str, str])

    def defer_startup_probes(self) -> None:
        """Treat both probes as just run so startup waits a full interval before probing."""
        started_at = time.monotonic()
        self.last_probe_monotonic = started_at
        self.last_analytics_probe_monotonic = started_at

    def seconds_since_probe(self) -> float | None:
        """Return the monotonic seconds since any probe last started.

        Returns:
            Elapsed seconds, or None before the first probe.
        """
        if self.last_probe_monotonic is None:
            return None
        return time.monotonic() - self.last_probe_monotonic

    def probe_due(self, interval_seconds: int) -> bool:
        """Report whether the safe usage probe is due.

        Returns:
            True before the first probe or once the interval has elapsed.
        """
        elapsed = self.seconds_since_probe()
        return elapsed is None or elapsed >= interval_seconds

    def analytics_probe_due(self, interval_seconds: int) -> bool:
        """Report whether the analytics probe is due.

        Returns:
            True before the first analytics probe or once the interval has elapsed.
        """
        if self.last_analytics_probe_monotonic is None:
            return True
        return time.monotonic() - self.last_analytics_probe_monotonic >= interval_seconds

    async def run_analytics_probe(self, source: StateSource, raw_accounts: list[JsonObject]) -> None:
        """Run the analytics probe, which also counts as the latest safe probe."""
        probe_started = time.monotonic()
        self.last_probe_monotonic = probe_started
        self.last_analytics_probe_monotonic = probe_started
        self.last_analytics_probe_errors = await asyncio.to_thread(source.probe_analytics, raw_accounts)
        self.last_probe_errors = self.last_analytics_probe_errors
        probed_at = utc_now()
        self.last_safe_probe_at = probed_at
        self.last_analytics_probe_at = probed_at

    async def run_safe_probe(self, source: StateSource, raw_accounts: list[JsonObject]) -> None:
        """Run the no-generation safe usage probe."""
        self.last_probe_monotonic = time.monotonic()
        self.last_probe_errors = await asyncio.to_thread(source.probe_accounts, raw_accounts)
        self.last_safe_probe_at = utc_now()


@dataclass
class RefreshRuntime:
    """Serialization lock, stop signal, and background task of the refresh loop."""

    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    loop_task: asyncio.Task[None] | None = None
