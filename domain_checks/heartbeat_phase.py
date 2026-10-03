# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing heartbeat scheduling and summary delivery within the current cycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Self, cast

from .dispatch_transport import redact_telegram_response, send_telegram_message_chunked
from .heartbeat_message import build_heartbeat_message

if TYPE_CHECKING:
    from datetime import tzinfo
    from types import TracebackType

    from httpx import AsyncClient

    from .common_check import DomainCheckResult
    from .cycle_channels import CycleChannels
    from .domain_entries import DomainEntryConfig
    from .event_bus_delivery import JsonObject, JsonValue
    from .heartbeat_settings import HeartbeatSettings

LOGGER = logging.getLogger("service-monitoring")


@dataclass
class ExternalSummaryBoundary:
    """Convert a completed optional registry failure into its existing diagnostic."""

    diagnostic: JsonObject | None = None

    def __enter__(self) -> Self:
        """Return this observation boundary with its prior diagnostic cleared."""
        self.diagnostic = None
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _traceback: TracebackType | None) -> bool:
        """Return true for ordinary observation failures; never consume cancellation."""
        if not isinstance(error, Exception):
            return False
        self.diagnostic = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        return True


@dataclass(frozen=True)
class ExternalHeartbeat:
    """The existing optional registry endpoint; no endpoint or token is allocated."""

    enabled: bool
    base_url: str
    token: str = field(repr=False)
    timeout_seconds: float

    async def read(self, client: AsyncClient) -> JsonObject | None:
        """Read only when a heartbeat is due and preserve existing failure summaries.

        Returns:
            The existing response mapping, diagnostic, or absent optional section.
        """
        if not self.enabled or not self.base_url:
            return None
        if not self.token:
            return {"ok": False, "error": "missing_e2e_registry_token"}
        boundary = ExternalSummaryBoundary()
        with boundary:
            response = await client.get(self.base_url.rstrip("/") + "/api/v1/status/summary",
                                        headers={"Authorization": f"Bearer {self.token}"},
                                        timeout=float(self.timeout_seconds))
            response.raise_for_status()
            data = cast("JsonValue", response.json())
            if isinstance(data, dict):
                return data
            return {"ok": False, "error": "invalid_e2e_registry_response"}
        return boundary.diagnostic


@dataclass(frozen=True)
class HeartbeatSchedule:
    """Keep the configured timezone, process start and existing per-time sent map."""

    timezone: tzinfo | None
    started_at: datetime
    tolerance_seconds: int
    sent: dict[str, str]


@dataclass(frozen=True)
class HeartbeatObservation:
    """Already gathered cycle observations; constructing a heartbeat performs no probes."""

    results: dict[str, DomainCheckResult]
    entries: dict[str, DomainEntryConfig]
    disabled: list[str]
    host_snapshot: JsonObject | None
    host_violations: list[str] | None
    slow: list[JsonObject] | None


@dataclass(frozen=True)
class HeartbeatPhase:
    """Retain configured order and mark an attempted heartbeat only after its transport returns."""

    settings: HeartbeatSettings
    schedule: HeartbeatSchedule
    external: ExternalHeartbeat

    async def run(self, channels: CycleChannels, observation: HeartbeatObservation) -> None:
        """Send at most one due heartbeat using only the existing configured transport."""
        if not self.settings.enabled or not (observation.results or observation.disabled):
            return
        now = datetime.now(self.schedule.timezone)
        today = now.date().isoformat()
        for configured in self.settings.times:
            label = configured.strftime("%H:%M")
            if self.schedule.sent.get(label) == today:
                continue
            scheduled = datetime(year=now.year, month=now.month, day=now.day, hour=configured.hour,
                                 minute=configured.minute, tzinfo=self.schedule.timezone)
            if scheduled <= now < scheduled + timedelta(seconds=self.schedule.tolerance_seconds):
                external = await self.external.read(channels.client)
                message = build_heartbeat_message(now=now, scheduled_label=f"{label} {self.settings.timezone}",
                    started_at=self.schedule.started_at, results=observation.results,
                    domain_entries=observation.entries,
                    disabled_lines=observation.disabled, host_snap=observation.host_snapshot,
                    host_violations=observation.host_violations, perf_slow=observation.slow, external_e2e=external)
                ok, responses = await send_telegram_message_chunked(channels.client, channels.telegram, message)
                self.schedule.sent[label] = today
                LOGGER.info("Heartbeat sent scheduled=%s ok=%s telegram_last=%s", label, ok,
                            redact_telegram_response(responses[-1] if responses else {}))
                break
