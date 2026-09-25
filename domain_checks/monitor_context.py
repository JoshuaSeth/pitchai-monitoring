# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared typed context and transition operations for monitor cycles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_checks.monitor_alerts import dispatch_prompt
from domain_checks.monitor_dispatch_models import DispatchRequest
from domain_checks.telegram import redact_telegram_response, send_telegram_message

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx

    from domain_checks.common_check import DomainCheckResult, DomainCheckSpec
    from domain_checks.monitor_dispatch import DispatchCoordinator
    from domain_checks.monitor_events import MonitorEvents
    from domain_checks.monitor_runtime_state import RuntimeState
    from domain_checks.monitor_settings import FeaturePolicy, MonitorSettings
    from domain_checks.telegram import TelegramConfig
    from domain_checks.types import JsonObject, JsonValue

    ChunkSender = Callable[
        [httpx.AsyncClient, TelegramConfig, str],
        Awaitable[tuple[bool, list[JsonObject]]],
    ]

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class Transition:
    """Effective status and edge flags after one observation."""

    effective_ok: bool
    degraded: bool
    recovered: bool
    fail_streak: int


@dataclass(frozen=True)
class DomainCycle:
    """Primary-domain results and inventory state for one monitor cycle."""

    started_ts: float
    results: dict[str, DomainCheckResult]
    enabled_specs: list[DomainCheckSpec]
    disabled_lines: list[str]
    browser_degraded: bool


@dataclass(frozen=True)
class Investigation:
    """Stable dispatcher identity and remediation boundaries."""

    state_key: str
    title: str
    subject: str
    scope: str


@dataclass
class MonitorContext:
    """Runtime dependencies shared by every feature-family cycle."""

    settings: MonitorSettings
    state: RuntimeState
    events: MonitorEvents
    dispatcher: DispatchCoordinator
    http_client: httpx.AsyncClient
    send_chunks: ChunkSender

    @property
    def alertable_domains(self) -> set[str]:
        """Return domains whose inventory policy permits Telegram alerts.

        Returns:
            The alertable domain names.
        """
        return {
            entry.domain
            for entry in self.settings.inventory.entries
            if entry.routes_telegram
        }

    def observe_global(
        self, name: str, *, observed_ok: bool, policy: FeaturePolicy,
    ) -> Transition:
        """Apply one observation to a global feature status.

        Returns:
            The resulting transition state.
        """
        status = self.state.global_signals[name]
        degraded, recovered = status.observe(
            observed_ok=observed_ok,
            down_after=policy.down_after_failures,
            up_after=policy.up_after_successes,
        )
        return Transition(
            effective_ok=status.last_ok,
            degraded=degraded,
            recovered=recovered,
            fail_streak=status.fail_streak,
        )

    def observe_domain(
        self, family: str, domain: str, *, observed_ok: bool, policy: FeaturePolicy,
    ) -> Transition:
        """Apply one observation to a per-domain feature status.

        Returns:
            The resulting transition state.
        """
        status = self.state.per_domain_signals[family]
        degraded, recovered = status.observe(
            domain,
            observed_ok=observed_ok,
            down_after=policy.down_after_failures,
            up_after=policy.up_after_successes,
        )
        return Transition(
            effective_ok=status.last_ok[domain],
            degraded=degraded,
            recovered=recovered,
            fail_streak=status.fail_streak[domain],
        )

    def append_signal(self, name: str, sample: list[JsonValue]) -> None:
        """Append a non-empty time-series sample."""
        if name and sample:
            self.state.collections.signal_history.setdefault(name, []).append(sample)

    async def alert(self, message: str) -> None:
        """Send and log a chunked operator alert."""
        telegram = self.settings.connections.telegram
        ok, responses = await self.send_chunks(self.http_client, telegram, message)
        LOGGER.warning(
            "Monitor alert sent_ok=%s telegram_last=%s",
            ok,
            redact_telegram_response(responses[-1] if responses else {}),
        )

    async def recovery(self, message: str) -> None:
        """Send and log a concise recovery notice."""
        ok, response = await send_telegram_message(
            self.http_client,
            self.settings.connections.telegram,
            message,
        )
        LOGGER.info(
            "Monitor recovery sent_ok=%s telegram=%s",
            ok,
            redact_telegram_response(response),
        )

    def dispatch(
        self,
        investigation: Investigation,
        evidence: JsonValue,
    ) -> None:
        """Schedule one deduplicated evidence-first dispatcher escalation."""
        prompt = dispatch_prompt(
            investigation.subject,
            evidence,
            remediation_scope=investigation.scope,
        )
        request = DispatchRequest(
            prompt=prompt,
            state_key=investigation.state_key,
            title=investigation.title,
        )
        self.dispatcher.schedule(request)
