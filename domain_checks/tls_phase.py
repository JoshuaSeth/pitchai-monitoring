# Copyright (c) 2026 PitchAI. All rights reserved.
"""TLS observation scheduling and existing per-domain routing policy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dispatch_metric_routes import dispatch_tls_and_forward
from .history_phase_context import HistoryComputeBoundary
from .message_tls_dns import build_tls_alert_message
from .metrics_tls import TlsCertCheckResult, check_tls_certs

if TYPE_CHECKING:
    from .health_state import HealthState
    from .network_settings import TlsSettings
    from .probe_frame import ProbeFrame, ProbeSchedule


@dataclass(frozen=True)
class TlsPhase:
    """Retain the current schedule and health objects across cycle attempts."""

    settings: TlsSettings
    health: HealthState
    schedule: ProbeSchedule

    async def run(self, frame: ProbeFrame) -> list[TlsCertCheckResult] | None:
        """Observe when due, record before sending, and preserve cancellation.

        Returns:
            All probe results, including muted domains, or None when skipped.
        """
        if not self.schedule.claim(enabled=self.settings.alerts.enabled, has_specs=bool(frame.domains.specs),
                                   interval_minutes=self.settings.interval_minutes):
            return None
        urls = {spec.domain: spec.url for spec in frame.domains.specs}
        results = [TlsCertCheckResult(domain="tls", ok=False, host=None, port=None, not_after_iso=None,
                                     days_remaining=None, error="tls_check_crashed", details={})]
        with HistoryComputeBoundary("TLS cert checks crashed"):
            results = await check_tls_certs(urls_by_domain=urls, min_days_valid=float(self.settings.min_days_valid),
                                           timeout_seconds=float(self.settings.timeout_seconds),
                                           concurrency=min(50, max(5, len(urls))))
        selected = frame.domains.select(results, "TLS")
        healthy = all(result.ok for result in selected)
        previous = bool(self.health.last_ok)
        down = self.health.advance(observed_ok=healthy, thresholds=self.settings.alerts)
        failures = [result for result in selected if not result.ok]
        failed = [result.domain for result in failures]
        frame.signals.append("tls", [float(frame.started), 1 if bool(self.health.last_ok) else 0, len(failed)])
        if down and selected and not healthy:
            frame.event("tls_degraded", float(frame.started), {"failures": len(failed), "domains": list(failed[:20])})
            await self._warn(frame, selected)
        if not previous and bool(self.health.last_ok):
            frame.event("tls_recovered", float(frame.started), {})
            if self.settings.alerts.notify_on_recovery:
                await frame.channels.recovery("TLS checks recovered ✅ (certificate issues cleared).",
                                              "TLS recovery notice sent_ok=%s telegram=%s")
        return results

    async def _warn(self, frame: ProbeFrame, results: list[TlsCertCheckResult]) -> None:
        """Use only the cycle's existing transport and dispatch ownership."""
        message = build_tls_alert_message(results=results, min_days_valid=float(self.settings.min_days_valid),
                                          down_after_failures=self.settings.alerts.down_after_failures,
                                          fail_streak=int(self.health.fail_streak))
        await frame.channels.notice(message, "TLS degraded alert sent_ok=%s telegram_last=%s")
        if self.settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "tls", "Dispatch already running for TLS; skipping new dispatch",
        ):
            frame.channels.tasks["tls"] = asyncio.create_task(dispatch_tls_and_forward(
                **frame.channels.dispatch_inputs(), results=results, min_days_valid=float(self.settings.min_days_valid),
            ))
