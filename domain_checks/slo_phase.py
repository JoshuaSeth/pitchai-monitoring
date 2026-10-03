# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing SLO history evaluation, debounce, warning and dispatch phase."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from .dispatch_metric_routes import dispatch_slo_and_forward
from .history_phase_context import HistoryComputeBoundary
from .history_phase_health import HistoryHealth
from .message_slo_red import build_slo_alert_message
from .metrics_slo import compute_slo_burn_violations

if TYPE_CHECKING:
    from .health_state import HealthState
    from .history_phase_context import HistoryFrame
    from .history_settings import SloSettings
    from .metrics_slo import SloBurnViolation


async def run_slo_phase(frame: HistoryFrame, settings: SloSettings, state: HealthState) -> None:
    """Process the current retained history using existing alert and task routes."""
    if not settings.alerts.enabled or not frame.history:
        return
    violations: list[SloBurnViolation] = []
    with HistoryComputeBoundary("SLO burn computation failed"):
        violations = compute_slo_burn_violations(
            history_by_domain=frame.history, now_ts=time.time(),
            slo_target_percent=float(settings.target_percent),
            burn_rate_rules=settings.rules,
            min_total_samples=int(settings.min_total_samples),
        )
    health = HistoryHealth(
        "slo", state, settings.alerts, frame,
        "SLO violations retained in domain history but excluded from Telegram routing domains=%s",
    )
    observation = health.observe(violations)
    if observation.alerted_down and observation.violations:
        routed = observation.violations
        frame.degraded("slo_degraded", [value.domain for value in routed])
        message = build_slo_alert_message(
            violations=routed, slo_target_percent=float(settings.target_percent),
            down_after_failures=settings.alerts.down_after_failures, fail_streak=int(state.fail_streak),
        )
        await frame.channels.warning(message, "SLO burn alert sent_ok=%s telegram_last=%s violations=%s",
                                     [value.domain for value in routed])
        if settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "slo", "Dispatch already running for SLO; skipping new dispatch",
        ):
            frame.channels.tasks["slo"] = asyncio.create_task(dispatch_slo_and_forward(
                **frame.channels.dispatch_inputs(), violations=routed,
                slo_target_percent=float(settings.target_percent),
            ))
    if not observation.previous and bool(state.last_ok):
        frame.recovered("slo_recovered")
        if settings.alerts.notify_on_recovery:
            await frame.channels.recovery("SLO burn recovered ✅ (burn-rate violations cleared).",
                                          "SLO burn recovery notice sent_ok=%s telegram=%s")
