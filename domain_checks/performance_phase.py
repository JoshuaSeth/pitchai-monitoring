# Copyright (c) 2026 PitchAI. All rights reserved.
"""Performance health transitions retaining unrelated-domain routing policy."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dispatch_domain_routes import dispatch_performance_and_forward
from .message_performance import build_performance_alert_message
from .performance import collect_performance_violations

if TYPE_CHECKING:
    from .common_check import DomainCheckResult
    from .event_bus_delivery import JsonObject
    from .health_state import HealthState
    from .probe_frame import ProbeFrame
    from .resource_settings import PerformanceSettings

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class PerformancePhase:
    """Use current thresholds, health and caller-owned per-domain results."""

    settings: PerformanceSettings
    health: HealthState

    async def run(self, frame: ProbeFrame, results: dict[str, DomainCheckResult]) -> list[JsonObject] | None:
        """Record performance transitions before existing notification effects.

        Returns:
            Current alertable slow domains, or None while disabled or empty.
        """
        if not self.settings.alerts.enabled or not results:
            return None
        slow = collect_performance_violations(
            results, http_elapsed_ms_max=self.settings.http_elapsed_ms_max,
            browser_elapsed_ms_max=self.settings.browser_elapsed_ms_max, per_domain_overrides=self.settings.overrides,
        )
        domains = [str(item.get("domain")) for item in slow]
        muted = set(domains) - frame.domains.alertable
        if muted:
            LOGGER.info("Performance violations retained in domain history "
                        "but excluded from Telegram routing domains=%s",
                        sorted(muted))
        slow = [item for item in slow if str(item.get("domain")) in frame.domains.alertable]
        previous = bool(self.health.last_ok)
        down = self.health.advance(observed_ok=not bool(slow), thresholds=self.settings.alerts)
        frame.signals.append("performance", [float(frame.started), 1 if bool(self.health.last_ok) else 0, len(slow)])
        if down and slow:
            fields: JsonObject = {"slow_domains": [entry.get("domain") for entry in slow[:20]]}
            frame.event("performance_degraded", float(frame.started), fields)
            await self._warn(frame, slow)
        if not previous and bool(self.health.last_ok):
            frame.event("performance_recovered", float(frame.started), {})
            if self.settings.alerts.notify_on_recovery:
                await frame.channels.recovery("Performance recovered ✅ (response times back under thresholds).",
                                              "Performance recovery notice sent_ok=%s telegram=%s")
        return slow

    async def _warn(self, frame: ProbeFrame, slow: list[JsonObject]) -> None:
        """Preserve the message, diagnostic log and conditional dispatch task."""
        message = build_performance_alert_message(slow=slow,
                                                  down_after_failures=self.settings.alerts.down_after_failures,
                                                  fail_streak=int(self.health.fail_streak))
        await frame.channels.warning(message, "Performance degraded alert sent_ok=%s telegram_last=%s slow_domains=%s",
                                     [entry.get("domain") for entry in slow[:5]])
        if self.settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "performance", "Dispatch already running for performance; skipping new dispatch",
        ):
            frame.channels.tasks["performance"] = asyncio.create_task(dispatch_performance_and_forward(
                **frame.channels.dispatch_inputs(), slow=slow,
            ))
