# Copyright (c) 2026 PitchAI. All rights reserved.
"""Apply per-domain health, inventory routing and dispatch in the native cycle."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .alert_transition import update_effective_ok
from .common_check import DomainCheckResult
from .dispatch_domain_routes import dispatch_and_forward
from .dispatch_state import dispatch_is_enabled
from .dispatch_transport import redact_telegram_response
from .domain_alerts import build_down_alert_message, route_domain_telegram_alert

if TYPE_CHECKING:
    from .cycle_channels import CycleChannels
    from .domain_entries import DomainEntryConfig
    from .event_bus_delivery import JsonObject
    from .history_phase_context import EventSink

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class DomainTransition:
    """One observation's prior/current health and retained failure count."""

    previous: bool
    current: bool
    failed: int
    alerted_down: bool


@dataclass(frozen=True)
class DomainHealth:
    """Reference the existing persisted domain counters and global thresholds."""

    last_ok: dict[str, bool]
    fail_streak: dict[str, int]
    success_streak: dict[str, int]
    down_after_failures: int
    up_after_successes: int

    def advance(self, result: DomainCheckResult) -> DomainTransition:
        """Update counters before any event, warning, dispatch or recovery.

        Returns:
            The native debounce edge, without changing the observation object.
        """
        domain = result.domain
        previous = self.last_ok.get(domain)
        if previous is None:
            previous = True
        current, failed, succeeded, down = update_effective_ok(
            prev_effective_ok=previous, observed_ok=bool(result.ok),
            fail_streak=int(self.fail_streak.get(domain, 0)),
            success_streak=int(self.success_streak.get(domain, 0)),
            down_after_failures=self.down_after_failures, up_after_successes=self.up_after_successes,
        )
        self.last_ok[domain] = current
        self.fail_streak[domain] = failed
        self.success_streak[domain] = succeeded
        return DomainTransition(previous, current, failed, down)


@dataclass(frozen=True)
class DomainResultPhase:
    """Keep original domain observations separate from delivery and investigation."""

    health: DomainHealth
    entries: dict[str, DomainEntryConfig]
    channels: CycleChannels
    event: EventSink

    async def observe(self, result: DomainCheckResult, started: float) -> None:
        """Apply the existing DOWN/recovery edge and suppressed-failure diagnostic."""
        transition = self.health.advance(result)
        if transition.alerted_down:
            await self._down(result, started, transition.failed)
            return
        if not transition.previous and bool(transition.current):
            self.event("domain_up", float(started), {"domain": result.domain})
        if result.ok is False and transition.previous is True and transition.current is True:
            LOGGER.warning(
                "Domain failing (alert suppressed) domain=%s fail_streak=%s/%s reason=%s details=%s",
                result.domain, transition.failed, self.health.down_after_failures, result.reason, result.details,
            )
        else:
            level = logging.INFO if result.ok else logging.WARNING
            LOGGER.log(level, "Domain result domain=%s ok=%s reason=%s details=%s",
                       result.domain, result.ok, result.reason, result.details)

    async def _down(self, result: DomainCheckResult, started: float, failed: int) -> None:
        """Persist the edge before routing the enriched, separately owned message."""
        entry = self.entries[result.domain]
        details = cast("JsonObject", result.details or {})
        error = details.get("error")
        self.event("domain_down", float(started), {
            "domain": result.domain, "reason": result.reason, "status_code": details.get("status_code"),
            "error": error[:800] if isinstance(error, str) else None, "fail_streak": int(failed),
            "telegram_alert": entry.routes_telegram, "alert_policy": entry.alert_policy.telegram,
        })
        enriched = DomainCheckResult(
            domain=result.domain, ok=result.ok, reason=result.reason,
            details={**(result.details or {}), "fail_streak": failed,
                     "down_after_failures": self.health.down_after_failures},
        )
        message = build_down_alert_message(enriched)
        routed = await route_domain_telegram_alert(http_client=self.channels.client,
                                                   telegram_cfg=self.channels.telegram,
                                                   entry=entry, message=message)
        if routed is not None:
            ok, responses = routed
            LOGGER.warning("Alert attempt domain=%s sent_ok=%s reason=%s telegram=%s details=%s",
                           result.domain, ok, result.reason,
                           redact_telegram_response(responses[-1] if responses else {}), enriched.details)
        self._dispatch(entry, enriched)

    def _dispatch(self, entry: DomainEntryConfig, result: DomainCheckResult) -> None:
        """Preserve inventory permission, existing tasks and unsent-result behavior."""
        channels = self.channels
        domain = result.domain
        if entry.routes_telegram and channels.dispatch_config and dispatch_is_enabled(
            channels.dispatch_config, channels.dispatch_state,
        ):
            if domain in channels.tasks and not channels.tasks[domain].done():
                LOGGER.info("Dispatch already running for domain=%s; skipping new dispatch", domain)
            else:
                channels.tasks[domain] = asyncio.create_task(dispatch_and_forward(
                    **channels.dispatch_inputs(), result=result,
                ))
        else:
            LOGGER.info("Dispatch not scheduled domain=%s alertable=%s enabled=%s reason=%s",
                        domain, entry.routes_telegram, bool(channels.dispatch_config and
                                                         channels.dispatch_state.get("enabled")),
                        channels.dispatch_state.get("disabled_reason"))
