# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scheduled container observations using the cycle's existing state and routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from .dispatch_probe_routes import dispatch_container_health_and_forward
from .history_phase_context import HistoryComputeBoundary
from .message_container import build_container_health_alert_message
from .metrics_container_health import ContainerHealthIssue, check_container_health

if TYPE_CHECKING:
    from .health_state import HealthState
    from .probe_frame import ProbeFrame, ProbeSchedule
    from .service_settings import ContainerSettings


@dataclass
class ContainerObservations:
    """Retain the current restart-count mapping, replacing it only after success."""

    restart_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ContainerPhase:
    """Preserve due time, inspection fallback, transition and send ordering."""

    settings: ContainerSettings
    health: HealthState
    schedule: ProbeSchedule
    observations: ContainerObservations

    async def run(self, frame: ProbeFrame) -> list[ContainerHealthIssue] | None:
        """Inspect containers when due without requiring an enabled domain.

        Returns:
            Current issues or None when disabled or not due.
        """
        if not self.schedule.claim(enabled=self.settings.alerts.enabled, has_specs=True,
                                   interval_minutes=self.settings.interval_minutes):
            return None
        issues = await self._observe()
        previous = bool(self.health.last_ok)
        down = self.health.advance(observed_ok=not bool(issues), thresholds=self.settings.alerts)
        frame.signals.append("container_health", [float(frame.started), 1 if self.health.last_ok else 0, len(issues)])
        if down and issues:
            frame.event("container_health_degraded", float(frame.started),
                        {"issues": [item.name for item in issues[:20]]})
            await self._warn(frame, issues)
        if not previous and bool(self.health.last_ok):
            frame.event("container_health_recovered", float(frame.started), {})
            if self.settings.alerts.notify_on_recovery:
                await frame.channels.recovery("Container health recovered ✅",
                                              "Container health recovery notice sent_ok=%s telegram=%s")
        return issues

    async def _observe(self) -> list[ContainerHealthIssue]:
        """Update the baseline only on a completed inspection.

        Returns:
            Inspection issues or the original global failure sentinel.
        """
        # The existing matcher normalizes each JSON pattern itself. Keep list
        # identity and values here instead of adding a second normalization.
        with HistoryComputeBoundary("Container health check crashed"):
            issues, counts = await check_container_health(
                docker_socket_path=self.settings.docker_socket_path,
                include_name_patterns=cast("list[str]", self.settings.selection.include_patterns),
                exclude_name_patterns=cast("list[str]", self.settings.selection.exclude_patterns),
                monitor_all=bool(self.settings.selection.monitor_all),
                previous_restart_counts=self.observations.restart_counts,
                timeout_seconds=float(self.settings.timeout_seconds),
            )
            self.observations.restart_counts = counts
            return issues
        return [ContainerHealthIssue(name="docker", container_id="", running=None, status=None,
                                     restart_count=None, restart_increase=None, oom_killed=None,
                                     health_status=None, exit_code=None, error="container_health_check_crashed")]

    async def _warn(self, frame: ProbeFrame, issues: list[ContainerHealthIssue]) -> None:
        """Use the unchanged existing warning and dispatch key."""
        message = build_container_health_alert_message(issues=issues,
            down_after_failures=self.settings.alerts.down_after_failures, fail_streak=int(self.health.fail_streak))
        await frame.channels.warning(message, "Container health degraded alert sent_ok=%s telegram_last=%s issues=%s",
                                     [item.name for item in issues])
        if self.settings.alerts.dispatch_on_degraded and frame.channels.dispatch_available(
            "container_health", "Dispatch already running for container_health; skipping new dispatch",
        ):
            frame.channels.tasks["container_health"] = asyncio.create_task(dispatch_container_health_and_forward(
                **frame.channels.dispatch_inputs(), issues=issues,
            ))
