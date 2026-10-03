# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the existing host-health phase with explicit state and delivery owners."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dispatch_domain_routes import dispatch_host_health_and_forward
from .host_snapshot import collect_host_snapshot
from .host_thresholds import build_host_health_alert_message, collect_host_health_violations, worst_disk

if TYPE_CHECKING:
    from .cycle_channels import CycleChannels
    from .event_bus_delivery import JsonObject
    from .health_state import HealthState
    from .history_phase_context import EventSink
    from .host_observations import HostObservations
    from .resource_settings import HostSettings
    from .signal_history import SignalHistory


@dataclass(frozen=True)
class HostPhase:
    """Use the cycle's current settings, health, readings and effect references."""

    settings: HostSettings
    health: HealthState
    observations: HostObservations
    channels: CycleChannels
    event: EventSink
    signals: SignalHistory

    async def run(self, started: float) -> tuple[JsonObject | None, list[str] | None]:
        """Observe, persist and route host health in the existing phase order.

        Returns:
            Current raw diagnostic snapshot and violations for this cycle's
            heartbeat, or two None values while the phase is disabled.
        """
        if not self.settings.alerts.enabled:
            return None, None
        snapshot = collect_host_snapshot(
            disk_paths=self.settings.disk_paths, cpu_prev_total=self.observations.cpu_prev_total,
            cpu_prev_idle=self.observations.cpu_prev_idle,
        )
        violations = collect_host_health_violations(
            snapshot, disk_used_percent_max=self.settings.disk_used_percent_max,
            mem_used_percent_max=self.settings.mem_used_percent_max,
            swap_used_percent_max=self.settings.swap_used_percent_max,
            cpu_used_percent_max=self.settings.cpu_used_percent_max,
            load1_per_cpu_max=self.settings.load1_per_cpu_max,
        )
        self.observations.advance_cpu(snapshot)
        previous = bool(self.health.last_ok)
        alerted_down = self.health.advance(observed_ok=not bool(violations), thresholds=self.settings.alerts)
        self.observations.capture(snapshot)
        _, disk_percent = worst_disk(snapshot)
        self.signals.append("host_health", [
            float(started), 1 if bool(self.health.last_ok) else 0,
            snapshot.get("mem_used_percent"), snapshot.get("swap_used_percent"),
            snapshot.get("cpu_used_percent"), snapshot.get("load1_per_cpu"), disk_percent, len(violations),
        ])
        if alerted_down and violations:
            self.event("host_health_degraded", float(started), {"violations": list(violations[:20])})
            await self._warn(snapshot, violations)
        if not previous and bool(self.health.last_ok):
            self.event("host_health_recovered", float(started), {})
            if self.settings.alerts.notify_on_recovery:
                await self.channels.recovery("Host health recovered ✅ (threshold violations cleared).",
                                             "Host health recovery notice sent_ok=%s telegram=%s")
        return snapshot, violations

    async def _warn(self, snapshot: JsonObject, violations: list[str]) -> None:
        """Keep the current warning route and running dispatch task ownership."""
        message = build_host_health_alert_message(
            violations=violations, snap=snapshot,
            down_after_failures=self.settings.alerts.down_after_failures,
            fail_streak=int(self.health.fail_streak),
        )
        await self.channels.warning(message, "Host health degraded alert sent_ok=%s telegram_last=%s violations=%s",
                                    violations)
        if self.settings.alerts.dispatch_on_degraded and self.channels.dispatch_available(
            "host_health", "Dispatch already running for host_health; skipping new dispatch",
        ):
            self.channels.tasks["host_health"] = asyncio.create_task(dispatch_host_health_and_forward(
                **self.channels.dispatch_inputs(), violations=violations, snap=snapshot,
            ))
