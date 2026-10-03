# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing Web Vitals schedule, threshold evaluation and domain-owned routing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .browser_admission import BrowserConnection
from .dispatch_probe_routes import dispatch_web_vitals_and_forward
from .message_browser import build_web_vitals_alert_message
from .vitals_evaluation import evaluate_vitals, thresholds_for

if TYPE_CHECKING:
    from .browser_phase_context import BrowserPhaseContext, BrowserProbeState
    from .browser_probe_contracts import VitalsProbe
    from .browser_probe_settings import VitalsSettings
    from .metrics_web_vitals import WebVitalsResult


@dataclass(frozen=True)
class VitalsPhase[BrowserT: BrowserConnection]:
    """Use the original per-domain maps and browser owned by the cycle."""

    settings: VitalsSettings
    state: BrowserProbeState
    probe: VitalsProbe[BrowserT]

    async def run(self, context: BrowserPhaseContext[BrowserT]) -> None:
        """Skip infrastructure failures after recording the attempt, without advancing health."""
        frame = context.frame
        if (not self.settings.alerts.enabled or not frame.domains.specs
                or context.admission.browser is None or context.degraded):
            return
        now = time.time()
        candidates = self.state.candidates(frame.domains.specs, now, self.settings.interval_minutes)
        dispatch_failures: list[WebVitalsResult] = []
        for spec in candidates[:int(self.settings.max_domains_per_cycle)]:
            self.state.last_run_ts[spec.domain] = now
            # The owning sequential cycle retains the admitted native Browser.
            result = await self.probe({"domain": spec.domain, "url": spec.url,
                "browser": context.admission.browser, "timeout_seconds": float(self.settings.timeout_seconds),
                "post_load_wait_ms": int(self.settings.post_load_wait_ms)})
            if not result.ok and bool(result.browser_infra_error):
                continue
            thresholds = thresholds_for(spec, self.settings.limits)
            evaluated = evaluate_vitals(result, thresholds)
            transition = self.state.advance(spec.domain, healthy=bool(evaluated.ok), alerts=self.settings.alerts)
            if transition.alerted_down and not evaluated.ok:
                if await self._warn(context, spec.domain, evaluated, thresholds):
                    dispatch_failures.append(evaluated)
            elif not transition.previous and bool(transition.current):
                frame.event("web_vitals_recovered", float(frame.started), {"domain": spec.domain})
                if self.settings.alerts.notify_on_recovery and context.entries[spec.domain].routes_telegram:
                    await context.recovery(spec.domain, "Web vitals", f"Web vitals recovered ✅ domain={spec.domain}")
        if (dispatch_failures and self.settings.alerts.dispatch_on_degraded
                and frame.channels.dispatch_available("web_vitals", "Dispatch already running for web_vitals; "
                                                      "skipping new dispatch")):
            frame.channels.tasks["web_vitals"] = asyncio.create_task(dispatch_web_vitals_and_forward(
                **frame.channels.dispatch_inputs(), failures=dispatch_failures,
            ))

    async def _warn(self, context: BrowserPhaseContext[BrowserT], domain: str, result: WebVitalsResult,
                    thresholds: dict[str, float | None]) -> bool:
        """Keep the result and thresholds intact through event, message and route.

        Returns:
            Whether the existing domain route handled the warning.
        """
        entry = context.entries[domain]
        context.frame.event("web_vitals_degraded", float(context.frame.started), {
            "domain": domain, "reason": str(result.error or "threshold_exceeded")[:500],
            "telegram_alert": entry.routes_telegram, "alert_policy": entry.alert_policy.telegram,
        })
        message = build_web_vitals_alert_message(failures=[result], thresholds=thresholds,
            down_after_failures=self.settings.alerts.down_after_failures,
            fail_streak=int(self.state.fail_streak[domain]))
        return await context.warning(domain, message, "Web vitals")
