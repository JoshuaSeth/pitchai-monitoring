# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing scheduled synthetic transactions, debounce and per-domain routing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .browser_admission import BrowserConnection
from .dispatch_probe_routes import dispatch_synthetic_and_forward
from .message_browser import build_synthetic_alert_message

if TYPE_CHECKING:
    from .browser_phase_context import BrowserPhaseContext, BrowserProbeState, BrowserProbeTransition
    from .browser_probe_contracts import SyntheticProbe
    from .browser_probe_settings import SyntheticSettings
    from .event_bus_delivery import JsonObject
    from .metrics_synthetic import SyntheticTransactionResult


@dataclass(frozen=True)
class SyntheticPhase[BrowserT: BrowserConnection]:
    """Keep attempted timestamps and counter dictionaries under the original cycle."""

    settings: SyntheticSettings
    state: BrowserProbeState
    probe: SyntheticProbe[BrowserT]

    async def run(self, context: BrowserPhaseContext[BrowserT]) -> None:
        """Run due transactions sequentially; cancellation retains each attempted timestamp."""
        frame = context.frame
        if (not self.settings.alerts.enabled or not frame.domains.specs
                or context.admission.browser is None or context.degraded):
            return
        now = time.time()
        specs = [spec for spec in frame.domains.specs if spec.synthetic_transactions]
        candidates = self.state.candidates(specs, now, self.settings.interval_minutes)
        dispatch_failures: list[SyntheticTransactionResult] = []
        for spec in candidates[:int(self.settings.max_domains_per_cycle)]:
            self.state.last_run_ts[spec.domain] = now
            # The owning sequential cycle retains the admitted native Browser.
            results = await self.probe({"domain": spec.domain, "base_url": spec.url,
                "browser": context.admission.browser,
                "transactions": cast("list[JsonObject]", spec.synthetic_transactions),
                "timeout_seconds": float(self.settings.timeout_seconds)})
            failed = [result for result in results if not result.ok]
            failures = [result for result in failed if not result.browser_infra_error]
            transition = self.state.advance(spec.domain, healthy=not bool(failures), alerts=self.settings.alerts)
            if transition.alerted_down and failures:
                if await self._warn(context, spec.domain, failures, transition):
                    dispatch_failures.extend(failures)
            elif not transition.previous and bool(transition.current):
                frame.event("synthetic_recovered", float(frame.started), {"domain": spec.domain})
                if self.settings.alerts.notify_on_recovery and context.entries[spec.domain].routes_telegram:
                    await context.recovery(spec.domain, "Synthetic",
                                           f"Synthetic transactions recovered ✅ domain={spec.domain}")
        if (dispatch_failures and self.settings.alerts.dispatch_on_degraded
                and frame.channels.dispatch_available("synthetic", "Dispatch already running for synthetic; "
                                                      "skipping new dispatch")):
            frame.channels.tasks["synthetic"] = asyncio.create_task(dispatch_synthetic_and_forward(
                **frame.channels.dispatch_inputs(), failures=dispatch_failures,
            ))

    async def _warn(self, context: BrowserPhaseContext[BrowserT], domain: str,
                    failures: list[SyntheticTransactionResult], transition: BrowserProbeTransition) -> bool:
        """Persist the event before routing and admitting dispatch failures.

        Returns:
            Whether the existing domain route handled the warning.
        """
        entry = context.entries[domain]
        context.frame.event("synthetic_degraded", float(context.frame.started), {
            "domain": domain, "failures": len(failures), "telegram_alert": entry.routes_telegram,
            "alert_policy": entry.alert_policy.telegram,
        })
        message = build_synthetic_alert_message(failures=failures,
            down_after_failures=self.settings.alerts.down_after_failures, fail_streak=int(transition.fail_streak))
        return await context.warning(domain, message, "Synthetic")
