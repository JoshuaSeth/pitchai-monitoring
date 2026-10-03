# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing post-cycle pipeline-health thresholds and escalation ordering."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dispatch_domain_routes import dispatch_meta_and_forward
from .message_templates import build_meta_alert_message

if TYPE_CHECKING:
    from .browser_admission import BrowserConnection
    from .event_bus_delivery import JsonObject
    from .health_state import HealthState
    from .probe_frame import ProbeFrame
    from .service_settings import MetaSettings


@dataclass(frozen=True)
class CycleTiming:
    """Already measured cycle values; browser connectivity is read only for dispatch."""

    interval: int
    elapsed: float
    write_failures: int
    browser: BrowserConnection | None
    check_concurrency: int
    browser_concurrency: int

    def dispatch_context(self) -> JsonObject:
        """Read the same connection status only after dispatch admission.

        Returns:
            The original six diagnostic fields without changing browser ownership.
        """
        connected = bool(self.browser and self.browser.is_connected()) if self.browser is not None else False
        return {"interval_seconds": int(self.interval), "elapsed_seconds": round(float(self.elapsed), 3),
                "state_write_fail_streak": int(self.write_failures), "browser_connected": connected,
                "check_concurrency": int(self.check_concurrency), "browser_concurrency": int(self.browser_concurrency)}


@dataclass(frozen=True)
class MetaPhase:
    """Record the original elapsed/write-failure health and effects after persistence."""

    settings: MetaSettings
    health: HealthState

    async def run(self, frame: ProbeFrame, timing: CycleTiming) -> None:
        """Apply pipeline thresholds without changing the cycle's sleep or writes."""
        if not self.settings.alerts.enabled:
            return
        reasons = self._reasons(timing)
        previous = bool(self.health.last_ok)
        down = self.health.advance(observed_ok=not bool(reasons), thresholds=self.settings.alerts)
        frame.signals.append("meta", [float(frame.started), 1 if self.health.last_ok else 0,
                                     len(reasons), round(float(timing.elapsed), 3), int(timing.write_failures)])
        if down and reasons:
            frame.event("meta_degraded", float(frame.started), {"reasons": list(reasons[:20])})
            message = build_meta_alert_message(reasons=reasons,
                down_after_failures=self.settings.alerts.down_after_failures, fail_streak=int(self.health.fail_streak))
            await frame.channels.warning(message, "Meta degraded alert sent_ok=%s telegram_last=%s reasons=%s",
                                         reasons[:3])
            if self.settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
                "meta", "Dispatch already running for meta; skipping new dispatch",
            ):
                frame.channels.tasks["meta"] = asyncio.create_task(dispatch_meta_and_forward(
                    **frame.channels.dispatch_inputs(), reasons=reasons, context=timing.dispatch_context(),
                ))
        if not previous and bool(self.health.last_ok):
            frame.event("meta_recovered", float(frame.started), {})
            if self.settings.alerts.notify_on_recovery:
                await frame.channels.recovery("Monitoring pipeline recovered ✅",
                                              "Meta recovery notice sent_ok=%s telegram=%s")

    def _reasons(self, timing: CycleTiming) -> list[str]:
        """Evaluate strict overrun and inclusive failed-write thresholds.

        Returns:
            Existing reason strings in overrun-then-write order.
        """
        threshold = float(timing.interval) * float(self.settings.cycle_overrun_factor)
        reasons: list[str] = []
        if float(timing.elapsed) > threshold:
            reasons.append(f"cycle_overrun: elapsed={round(float(timing.elapsed), 3)}s > "
                           f"threshold={round(threshold, 3)}s interval={int(timing.interval)}s")
        if int(timing.write_failures) >= int(self.settings.state_write_failures_max):
            reasons.append(f"state_write_failures: streak={int(timing.write_failures)} >= "
                           f"{int(self.settings.state_write_failures_max)}")
        return reasons
