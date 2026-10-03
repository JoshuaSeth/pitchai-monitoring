# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native API-contract scheduling and routing, without new readiness probes."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from .alert_transition import update_effective_ok
from .dispatch_api_contract import dispatch_api_contract_and_forward
from .dispatch_transport import redact_telegram_response, send_telegram_message
from .domain_alerts import route_domain_telegram_alert
from .message_api_contract import build_api_contract_alert_message

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    from httpx import AsyncClient

    from .api_contract_settings import ApiContractSettings
    from .browser_phase_context import BrowserProbeState
    from .domain_entries import DomainEntryConfig
    from .event_bus_delivery import JsonObject
    from .metrics_api_contract import ApiContractCheckResult
    from .probe_frame import ProbeFrame

LOGGER = logging.getLogger("service-monitoring")


class ApiContractCall(TypedDict):
    """The existing native probe's complete named input contract."""

    http_client: AsyncClient
    domain: str
    base_url: str
    checks: list[JsonObject]
    timeout_seconds: float


@dataclass(frozen=True)
class ApiContractPhase:
    """Retain attempted timestamps and task order across per-domain observations."""

    settings: ApiContractSettings
    state: BrowserProbeState
    entries: Mapping[str, DomainEntryConfig]
    probe: Callable[[ApiContractCall], Coroutine[None, None, list[ApiContractCheckResult]]]

    async def run(self, frame: ProbeFrame) -> None:
        """Observe only existing due checks, preserving error and cancellation edges."""
        if not self.settings.alerts.enabled or not frame.domains.specs:
            return
        now = time.time()
        specs = frame.domains.specs
        configured = [spec for spec in specs if spec.api_contract_checks]
        due = [spec for spec in configured
               if now - float(self.state.last_run_ts.get(spec.domain, 0.0)) >= self.settings.interval_minutes * 60]
        if not due:
            return
        tasks: dict[str, asyncio.Task[list[ApiContractCheckResult]]] = {}
        for spec in due[:50]:
            self.state.last_run_ts[spec.domain] = now
            inputs: ApiContractCall = {"http_client": frame.channels.client, "domain": spec.domain,
                                      "base_url": spec.url, "checks": spec.api_contract_checks,
                                      "timeout_seconds": float(self.settings.timeout_seconds)}
            tasks[spec.domain] = asyncio.create_task(self.probe(inputs))
        failures: list[ApiContractCheckResult] = []
        for domain, task in tasks.items():
            results = await task
            failures.extend(await self._observe(frame, domain, results))
        if failures and self.settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "api_contract", "Dispatch already running for api_contract; skipping new dispatch",
        ):
            frame.channels.tasks["api_contract"] = asyncio.create_task(dispatch_api_contract_and_forward(
                **frame.channels.dispatch_inputs(), failures=failures,
            ))

    async def _observe(self, frame: ProbeFrame, domain: str,
                       results: list[ApiContractCheckResult]) -> list[ApiContractCheckResult]:
        """Apply the original transition before recording, routing or dispatch.

        Returns:
            Failures belonging to an alertable domain on its debounced down edge.
        """
        healthy = True
        if results:
            healthy = all(result.ok for result in results)
        previous = self.state.last_ok.get(domain, True)
        current, failed, succeeded, down = update_effective_ok(
            prev_effective_ok=bool(previous), observed_ok=healthy,
            fail_streak=int(self.state.fail_streak.get(domain, 0)),
            success_streak=int(self.state.success_streak.get(domain, 0)),
            down_after_failures=self.settings.alerts.down_after_failures,
            up_after_successes=self.settings.alerts.up_after_successes,
        )
        self.state.last_ok[domain] = current
        self.state.fail_streak[domain] = failed
        self.state.success_streak[domain] = succeeded
        if down:
            return await self._down(frame, domain, results, failed)
        if not previous and current:
            frame.event("api_contract_recovered", float(frame.started), {"domain": domain})
            if self.settings.alerts.notify_on_recovery and self.entries[domain].routes_telegram:
                ok, response = await send_telegram_message(
                    frame.channels.client, frame.channels.telegram, f"API contract checks recovered ✅ domain={domain}",
                )
                LOGGER.info("API contract recovery notice sent_ok=%s telegram=%s domain=%s",
                            ok, redact_telegram_response(response), domain)
        return []

    async def _down(self, frame: ProbeFrame, domain: str,
                    results: list[ApiContractCheckResult], failed: int) -> list[ApiContractCheckResult]:
        """Keep event-before-transport ordering and the inventory's existing audience.

        Returns:
            Original failures for an alertable domain, otherwise an empty list.
        """
        entry = self.entries[domain]
        failures = [result for result in results if not result.ok]
        frame.event("api_contract_degraded", float(frame.started), {
            "domain": domain, "failures": len(failures), "telegram_alert": entry.routes_telegram,
            "alert_policy": entry.alert_policy.telegram,
        })
        message = build_api_contract_alert_message(failures=failures,
            down_after_failures=self.settings.alerts.down_after_failures, fail_streak=int(failed))
        routed = await route_domain_telegram_alert(http_client=frame.channels.client,
            telegram_cfg=frame.channels.telegram, entry=entry, message=message)
        if routed is not None:
            ok, responses = routed
            LOGGER.warning("API contract degraded domain=%s sent_ok=%s telegram_last=%s",
                           domain, ok, redact_telegram_response(responses[-1] if responses else {}))
        return failures if entry.routes_telegram else []
