# Copyright (c) 2026 PitchAI. All rights reserved.
"""DNS scheduling, drift baselines and existing notification transitions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .dispatch_metric_routes import dispatch_dns_and_forward
from .history_phase_context import HistoryComputeBoundary
from .message_tls_dns import build_dns_alert_message
from .metrics_dns import DnsCheckResult, check_dns

if TYPE_CHECKING:
    from .health_state import HealthState
    from .network_settings import DnsSettings
    from .probe_frame import ProbeFrame, ProbeSchedule


@dataclass(frozen=True)
class DnsPhase:
    """Own references to persisted DNS state without allocating a resolver."""

    settings: DnsSettings
    health: HealthState
    schedule: ProbeSchedule
    last_ips: dict[str, list[str]]

    def _expected(self) -> dict[str, list[str]]:
        """Normalize keys while leaving legacy value normalization in check_dns.

        Returns:
            Existing values, retaining lists and wrapping scalar JSON values.
        """
        expected: dict[str, list[str]] = {}
        for key, value in self.settings.drift.expected_ips_by_domain.items():
            name = str(key or "").strip().lower()
            if name:
                # The existing checker normalizes each JSON item to a string.
                expected[name] = cast("list[str]", value if isinstance(value, list) else [value])
        return expected

    def _drift(self, domains: list[str]) -> dict[str, bool]:
        """Apply default and explicit drift flags with original key precedence.

        Returns:
            Lowercase domain flags without filtering unknown configured keys.
        """
        result = dict.fromkeys((domain.lower() for domain in domains), bool(self.settings.drift.alert_on_drift_default))
        for key, value in self.settings.drift.alert_on_drift_by_domain.items():
            name = str(key or "").strip().lower()
            if name:
                result[name] = bool(value)
        return result

    async def _observe(self, domains: list[str]) -> list[DnsCheckResult]:
        """Preserve the loud synthetic DNS failure result on ordinary exceptions.

        Returns:
            Actual results or the original single dns_check_crashed result.
        """
        expected = self._expected()
        drift = self._drift(domains)
        with HistoryComputeBoundary("DNS checks crashed"):
            return await check_dns(domains=domains, resolvers=self.settings.resolvers,
                                      timeout_seconds=float(self.settings.timeout_seconds),
                                      require_ipv4=bool(self.settings.require_ipv4),
                                      require_ipv6=bool(self.settings.require_ipv6),
                                      previous_ips_by_domain=self.last_ips,
                                      expected_ips_by_domain=expected, alert_on_drift_by_domain=drift)
        return [DnsCheckResult(domain="dns", ok=False, a_records=[], aaaa_records=[],
                               error="dns_check_crashed", drift_detected=False, expected_ips=None)]

    async def run(self, frame: ProbeFrame) -> list[DnsCheckResult] | None:
        """Update drift before routing, with attempted time retained on failure.

        Returns:
            All current results, or None when no observation is due.
        """
        if not self.schedule.claim(enabled=self.settings.alerts.enabled, has_specs=bool(frame.domains.specs),
                                   interval_minutes=self.settings.interval_minutes):
            return None
        domains = [spec.domain for spec in frame.domains.specs]
        results = await self._observe(domains)
        for result in results:
            self.last_ips[result.domain] = sorted(set((result.a_records or []) + (result.aaaa_records or [])))
        selected = frame.domains.select(results, "DNS")
        healthy = all(result.ok for result in selected)
        previous = bool(self.health.last_ok)
        down = self.health.advance(observed_ok=healthy, thresholds=self.settings.alerts)
        failures = [result for result in selected if not result.ok]
        failed = [result.domain for result in failures]
        frame.signals.append("dns", [float(frame.started), 1 if bool(self.health.last_ok) else 0, len(failed)])
        if down and selected and not healthy:
            frame.event("dns_degraded", float(frame.started), {"failures": len(failed), "domains": list(failed[:20])})
            await self._warn(frame, selected)
        if not previous and bool(self.health.last_ok):
            frame.event("dns_recovered", float(frame.started), {})
            if self.settings.alerts.notify_on_recovery:
                await frame.channels.recovery("DNS checks recovered ✅ (resolution issues cleared).",
                                              "DNS recovery notice sent_ok=%s telegram=%s")
        return results

    async def _warn(self, frame: ProbeFrame, results: list[DnsCheckResult]) -> None:
        """Preserve warning-before-dispatch order and existing active tasks."""
        message = build_dns_alert_message(results=results, down_after_failures=self.settings.alerts.down_after_failures,
                                          fail_streak=int(self.health.fail_streak))
        await frame.channels.notice(message, "DNS degraded alert sent_ok=%s telegram_last=%s")
        if self.settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "dns", "Dispatch already running for DNS; skipping new dispatch",
        ):
            frame.channels.tasks["dns"] = asyncio.create_task(dispatch_dns_and_forward(
                **frame.channels.dispatch_inputs(), results=results,
            ))
