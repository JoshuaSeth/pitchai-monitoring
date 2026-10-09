# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain browser-probe counters and existing inventory-owned delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .alert_transition import update_effective_ok
from .browser_admission import BrowserConnection
from .dispatch_transport import redact_telegram_response, send_telegram_message
from .domain_alerts import route_domain_telegram_alert

if TYPE_CHECKING:
    from .alert_settings import AlertSettings
    from .browser_admission import BrowserAdmission
    from .common_check import DomainCheckSpec
    from .domain_entries import DomainEntryConfig
    from .probe_frame import ProbeFrame

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class BrowserProbeTransition:
    """One observation's unchanged effective-health transition."""

    previous: bool
    current: bool
    fail_streak: int
    alerted_down: bool


@dataclass(frozen=True)
class BrowserProbeState:
    """Reference the existing persisted dictionaries without adopting new state."""

    last_ok: dict[str, bool]
    fail_streak: dict[str, int]
    success_streak: dict[str, int]
    last_run_ts: dict[str, float]

    def advance(self, domain: str, *, healthy: bool, alerts: AlertSettings) -> BrowserProbeTransition:
        """Update the same three mappings before any event or outgoing operation.

        Returns:
            Previous/current health, failure count and downward transition.
        """
        previous = self.last_ok.get(domain, True)
        current, failed, succeeded, down = update_effective_ok(
            prev_effective_ok=bool(previous), observed_ok=healthy,
            fail_streak=int(self.fail_streak.get(domain, 0)),
            success_streak=int(self.success_streak.get(domain, 0)),
            down_after_failures=alerts.down_after_failures, up_after_successes=alerts.up_after_successes,
        )
        self.last_ok[domain] = current
        self.fail_streak[domain] = failed
        self.success_streak[domain] = succeeded
        return BrowserProbeTransition(previous, current, failed, down)

    def candidates(self, specs: list[DomainCheckSpec], now: float, interval: int) -> list[DomainCheckSpec]:
        """Retain stable least-recently-attempted order at the inclusive interval.

        Returns:
            Due specs without advancing any attempt timestamp.
        """
        due = [spec for spec in specs
               if now - float(self.last_run_ts.get(spec.domain, 0.0)) >= float(interval * 60)]
        due.sort(key=lambda spec: float(self.last_run_ts.get(spec.domain, 0.0)))
        return due


@dataclass(frozen=True)
class BrowserPhaseContext[BrowserT: BrowserConnection]:
    """Cycle-owned browser and domain routes, with no new receiver or audience."""

    frame: ProbeFrame
    entries: dict[str, DomainEntryConfig]
    admission: BrowserAdmission[BrowserT]
    degraded: bool

    async def warning(self, domain: str, message: str, label: str) -> bool:
        """Route under the existing domain policy and preserve unsent-result logging.

        Returns:
            Whether the existing route produced a result, regardless of delivery success.
        """
        channels = self.frame.channels
        routed = await route_domain_telegram_alert(http_client=channels.client, telegram_cfg=channels.telegram,
                                                   entry=self.entries[domain], message=message)
        if routed is None:
            return False
        ok, responses = routed
        LOGGER.warning("%s degraded domain=%s sent_ok=%s telegram_last=%s", label, domain, ok,
                       redact_telegram_response(responses[-1] if responses else {}))
        return True

    async def recovery(self, domain: str, label: str, message: str) -> None:
        """Preserve the single-message recovery route and its original diagnostic."""
        channels = self.frame.channels
        ok, response = await send_telegram_message(channels.client, channels.telegram, message)
        LOGGER.info("%s recovery notice sent_ok=%s telegram=%s domain=%s",
                    label, ok, redact_telegram_response(response), domain)
