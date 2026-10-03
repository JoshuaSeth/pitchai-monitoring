# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing proxy health transitions with DFT coverage retained as a recovery gate."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dispatch_probe_routes import dispatch_proxy_and_forward
from .message_proxy import build_proxy_alert_message

if TYPE_CHECKING:
    from .common_check import DomainCheckResult
    from .health_state import HealthState
    from .probe_frame import ProbeFrame
    from .proxy_observation import ProxyObservation, ProxyReader


@dataclass(frozen=True)
class ProxyPhase:
    """Preserve global access rates, per-domain routing and unresolved coverage."""

    reader: ProxyReader
    health: HealthState

    async def run(self, frame: ProbeFrame, results: dict[str, DomainCheckResult]) -> None:
        """Observe only when enabled and domain observations exist."""
        settings = self.reader.settings
        if not settings.alerts.enabled or not results:
            return
        observation = self.reader.read(frame.domains, results)
        healthy = (not observation.issues and not observation.access_violation
                   and not observation.upstream_violation and (self.reader.dft.coverage_ok or self.health.last_ok))
        previous = bool(self.health.last_ok)
        down = self.health.advance(observed_ok=healthy, thresholds=settings.alerts)
        percent, total, bad = observation.counters()
        frame.signals.append("proxy", [float(frame.started), 1 if self.health.last_ok else 0,
            len(observation.issues), percent, total, bad, len(observation.upstream)])
        if down and not healthy:
            frame.event("proxy_degraded", float(frame.started), {
                "upstream_issues": len(observation.issues), "access_502_504_percent": percent,
                "upstream_events": len(observation.upstream),
            })
            await self._warn(frame, observation)
        if not previous and bool(self.health.last_ok):
            frame.event("proxy_recovered", float(frame.started), {})
            if settings.alerts.notify_on_recovery:
                await frame.channels.recovery("Proxy/upstream signals recovered ✅",
                                              "Proxy recovery notice sent_ok=%s telegram=%s")

    async def _warn(self, frame: ProbeFrame, observation: ProxyObservation) -> None:
        """Keep existing message inputs and dispatch identity without new routing."""
        settings = self.reader.settings
        message = build_proxy_alert_message(
            upstream_issues=observation.issues, access_stats=observation.access,
            upstream_errors_summary=observation.summary, window_seconds=int(settings.feed.window_seconds),
            down_after_failures=settings.alerts.down_after_failures, fail_streak=int(self.health.fail_streak),
        )
        await frame.channels.notice(message, "Proxy degraded alert sent_ok=%s telegram_last=%s")
        if settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "proxy", "Dispatch already running for proxy; skipping new dispatch",
        ):
            frame.channels.tasks["proxy"] = asyncio.create_task(dispatch_proxy_and_forward(
                **frame.channels.dispatch_inputs(), upstream_issues=observation.issues,
                access_stats=observation.access, upstream_error_events=observation.upstream,
                window_seconds=int(settings.feed.window_seconds),
            ))
