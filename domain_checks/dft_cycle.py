# Copyright (c) 2026 PitchAI. All rights reserved.
"""DFT consumer called by the existing service-monitoring cycle."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .dft_checker_process import observe_checker
from .dft_cutover_config import parse_cutover_boundary
from .dft_handoff import DftHandoff
from .dft_journal import DftJournal
from .metrics_nginx import compute_access_window_stats

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from .dft_access_cutover import DftAccessCutover
    from .dft_cutover_config import CutoverBoundary
    from .dft_journal import PendingTransition
    from .event_bus_delivery import JsonValue
    from .metrics_nginx import NginxAccessWindowStats

_PRODUCTION_ROOT = Path("/var/log/nginx/dft-access-v1/production")
_DELIVERY_TIMEOUT_SECONDS = 10


type TransitionReceiver = Callable[[PendingTransition], Awaitable[str | None]]


@dataclass(frozen=True)
class DftCycleConfig:
    """Source proposal only; every executable/mount path needs host admission."""

    mode: Literal["shared", "segments"]
    source_root: Path
    retention_config: Path
    journal_path: Path
    acknowledged_incident_id: str | None = None
    cutover: CutoverBoundary | None = None


def _absolute_path(settings: dict[str, JsonValue], key: str) -> Path:
    value = settings.get(key)
    if isinstance(value, str) and Path(value).is_absolute() and ".." not in Path(value).parts:
        return Path(value)
    message = f"dft_invalid_allocation_{key}"
    raise ValueError(message)


def parse_cycle_config(value: JsonValue) -> DftCycleConfig | None:
    """Require an explicit admitted allocation; default configuration is disabled.

    Returns:
        No consumer unless enabled, otherwise the validated source allocation.

    Raises:
        ValueError: Enabled settings are incomplete or ambiguous.
    """
    if value is None or (isinstance(value, dict) and value.get("enabled") is False):
        return None
    if not isinstance(value, dict) or value.get("enabled") is not True:
        message = "dft_invalid_enabled_setting"
        raise ValueError(message)
    mode = value.get("mode")
    acknowledgement = value.get("acknowledged_incident_id")
    if not isinstance(mode, str) or mode not in {"shared", "segments"} or (
        acknowledgement is not None and not isinstance(acknowledgement, str)
    ):
        message = "dft_invalid_mode_or_acknowledgement"
        raise ValueError(message)
    return DftCycleConfig("segments" if mode == "segments" else "shared", _absolute_path(value, "source_root"),
                          _absolute_path(value, "retention_config"), _absolute_path(value, "journal_path"),
                          acknowledgement, parse_cutover_boundary(value.get("cutover")) if mode == "segments" else None)


class DftCycle:
    """Integrate reads, atomic local intents and an explicitly supplied receiver."""

    def __init__(self, config: DftCycleConfig | None, receiver: TransitionReceiver | None = None) -> None:
        """Keep disabled runs free of additional state files or subprocesses."""
        self.config: DftCycleConfig | None = config
        self.receiver: TransitionReceiver | None = receiver
        self.journal: DftJournal | None = DftJournal(config.journal_path) if config else None
        self.handoff: DftHandoff | None = None
        with ExitStack() as cleanup:
            if config is not None and self.journal is not None:
                cleanup.callback(self.journal.close)
                self.handoff = DftHandoff(config.mode, config.cutover, self.journal, _PRODUCTION_ROOT)
            cleanup.pop_all()
        self.coverage_ok: bool = config is None
        self._coverage_pending: bool = False
        self.summary: dict[str, JsonValue] = {"enabled": config is not None}

    @property
    def access(self) -> DftAccessCutover | None:
        """Expose the selected feed from the handoff's single source of authority."""
        return self.handoff.access if self.handoff is not None else None

    def close(self) -> None:
        """Close only the consumer-owned journal on cycle shutdown."""
        if self.journal is not None:
            self.journal.close()

    def read_access(
        self, *, access_log_path: str, now: datetime, window_seconds: int, max_bytes: int,
    ) -> NginxAccessWindowStats | None:
        """Use the selected feed and retain coverage failure independently.

        Returns:
            Complete counters, or None while the configured coverage is unavailable.
        """
        if self.access is None:
            return compute_access_window_stats(access_log_path=access_log_path, now=now,
                                               window_seconds=window_seconds, max_bytes=max_bytes)
        result = None
        with suppress(OSError, ValueError):
            result = self.access.read(access_log_path=access_log_path, now=now,
                                      window_seconds=window_seconds, max_bytes=max_bytes)
        self.coverage_ok = result is not None
        self._coverage_pending = True
        if self.handoff is not None:
            self.handoff.record_read(now=now.timestamp(), covered=self.coverage_ok,
                                     window_seconds=window_seconds, max_bytes=max_bytes)
        if self.journal is not None:
            self.journal.save_segments(self.access.snapshots)
        return result

    async def observe(self, *, now: float) -> None:
        """Run once in the existing cycle; persist before attempting any receipt."""
        if self.config is None or self.journal is None:
            return
        coverage_current = self.coverage_ok and self._coverage_pending
        self._coverage_pending = False
        observation = await observe_checker(self.config.source_root, self.config.retention_config)
        if self.handoff is not None:
            self.handoff.observe(now=now, checker_healthy=observation.healthy and coverage_current)
            if self.handoff.pending:
                observation = replace(observation, errors=(*observation.errors, "segment_cutover_pending"))
        if not coverage_current:
            observation = replace(observation, errors=(*observation.errors, "access_window_unavailable"))
        incident = self.journal.record(observation, now=now,
                                       acknowledged_incident_id=self.config.acknowledged_incident_id)
        await self.deliver_pending(now=now)
        self.summary = {
            "enabled": True, "healthy": observation.healthy, "errors": list(observation.errors),
            "age_seconds": observation.age_seconds, "overdue_segments": observation.overdue_segments,
            "incident_id": incident.incident_id if incident else None,
            "incident_closed_at": incident.closed_at if incident else None,
            "delivery_route_allocated": self.receiver is not None,
            "active_access_source": self.access.mode if self.access is not None else None,
        }

    async def deliver_pending(self, *, now: float) -> None:
        """Bound the oldest due attempt; a timeout retains uncertainty and bytes."""
        if self.journal is None or self.receiver is None:
            return
        pending = self.journal.pending(now=now)
        if pending is None:
            return
        receipt = None
        with suppress(OSError):
            async with asyncio.timeout(_DELIVERY_TIMEOUT_SECONDS):
                receipt = await self.receiver(pending)
        self.journal.settle(pending.delivery_id, receiver_id=receipt, now=now)
