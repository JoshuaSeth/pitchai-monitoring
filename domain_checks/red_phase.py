# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing RED history evaluation, debounce, warning and dispatch phase."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from .dispatch_metric_routes import dispatch_red_and_forward
from .history_phase_context import HistoryComputeBoundary
from .history_phase_health import HistoryHealth
from .message_slo_red import build_red_alert_message
from .metrics_red import compute_red_violations

if TYPE_CHECKING:
    from .health_state import HealthState
    from .history_phase_context import HistoryFrame
    from .history_settings import RedSettings
    from .metrics_red import RedViolation


async def run_red_phase(frame: HistoryFrame, settings: RedSettings, state: HealthState) -> None:
    """Process recorded RED signals without changing the current delivery policy."""
    if not settings.alerts.enabled or not frame.history:
        return
    violations: list[RedViolation] = []
    with HistoryComputeBoundary("RED computation failed"):
        violations = compute_red_violations(
            history_by_domain=frame.history, now_ts=time.time(), window_minutes=int(settings.window_minutes),
            min_samples=int(settings.min_samples), error_rate_max_percent=settings.error_rate_max_percent,
            http_p95_ms_max=settings.http_p95_ms_max, browser_p95_ms_max=settings.browser_p95_ms_max,
        )
    health = HistoryHealth(
        "red", state, settings.alerts, frame,
        "RED violations retained in domain history but excluded from Telegram routing domains=%s",
    )
    observation = health.observe(violations)
    if observation.alerted_down and observation.violations:
        routed = observation.violations
        frame.degraded("red_degraded", [value.domain for value in routed])
        message = build_red_alert_message(
            violations=routed, window_minutes=int(settings.window_minutes),
            down_after_failures=settings.alerts.down_after_failures, fail_streak=int(state.fail_streak),
        )
        await frame.channels.warning(message, "RED degraded alert sent_ok=%s telegram_last=%s domains=%s",
                                     [value.domain for value in routed])
        if settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "red", "Dispatch already running for RED; skipping new dispatch",
        ):
            frame.channels.tasks["red"] = asyncio.create_task(dispatch_red_and_forward(
                **frame.channels.dispatch_inputs(), violations=routed, window_minutes=int(settings.window_minutes),
            ))
    if not observation.previous and bool(state.last_ok):
        frame.recovered("red_recovered")
        if settings.alerts.notify_on_recovery:
            await frame.channels.recovery("RED signals recovered ✅ (error-rate/latency back under thresholds).",
                                          "RED recovery notice sent_ok=%s telegram=%s")
