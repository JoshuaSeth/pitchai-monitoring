# Copyright (c) 2026 PitchAI. All rights reserved.
"""One ordered native cycle, retaining all observation and persistence boundaries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .browser_admission import BrowserConnection
from .browser_phase_context import BrowserPhaseContext
from .heartbeat_phase import HeartbeatObservation
from .history_phase_context import HistoryComputeBoundary, HistoryFrame
from .probe_frame import ProbeDomains, ProbeFrame
from .red_phase import run_red_phase
from .slo_phase import run_slo_phase

if TYPE_CHECKING:
    from .cycle_channels import CycleChannels
    from .cycle_persistence import CyclePersistence
    from .cycle_phases import CyclePhases
    from .domain_entries import DomainEntryConfig
    from .signal_history import SignalHistory


@dataclass(frozen=True)
class CycleParticipants:
    """The same startup inventory lookup and alertable set used by each phase."""

    entries: dict[str, DomainEntryConfig]
    alertable: set[str]


@dataclass(frozen=True)
class CycleIteration[BrowserT: BrowserConnection]:
    """Execute phases sequentially, leaving scheduling and final cleanup to the owner."""

    participants: CycleParticipants
    channels: CycleChannels
    persistence: CyclePersistence
    phases: CyclePhases[BrowserT]
    signals: SignalHistory

    async def run(self, started: float) -> ProbeFrame:
        """Retain domain-to-heartbeat order and persist after DFT and outbox observation.

        Returns:
            This cycle's probe frame for the original post-cycle meta phase.

        Failed/cancelled phases propagate immediately; later observations do not
        run, and no synthetic success or blanket cleanup is introduced here.
        """
        observation = await self.phases.domains.run(started)
        history = self.phases.history
        history_frame = HistoryFrame(self.persistence.records.history, self.participants.alertable,
                                     started, self.channels, self.persistence.event, self.signals)
        await run_slo_phase(history_frame, history.slo_settings, history.slo_health)
        await run_red_phase(history_frame, history.red_settings, history.red_health)
        metrics = self.phases.metrics
        host_snapshot, host_violations = await metrics.host.run(started)
        frame = ProbeFrame(started, ProbeDomains(observation.specs, set(self.participants.entries),
                                               self.participants.alertable),
                           self.channels, self.persistence.event, self.signals)
        slow = await metrics.performance.run(frame, observation.results)
        _ = await metrics.tls.run(frame)
        _ = await metrics.dns.run(frame)
        await metrics.api.run(frame)
        _ = await metrics.container.run(frame)
        await metrics.proxy.run(frame, observation.results)
        browser = self.phases.domains.browser
        context = BrowserPhaseContext(frame, self.participants.entries, browser, observation.browser_degraded)
        await self.phases.browser.synthetic.run(context)
        await self.phases.browser.vitals.run(context)
        await self.phases.browser.recovery.run(frame, degraded=observation.browser_degraded)
        self.channels.prune_completed()
        await self.phases.heartbeat.run(self.channels, HeartbeatObservation(
            observation.results, self.participants.entries, observation.disabled_lines, host_snapshot, host_violations,
            slow if metrics.performance.settings.alerts.enabled else None,
        ))
        await self.persistence.dft.observe(now=time.time())
        with HistoryComputeBoundary("Failed to prune signal history"):
            self.signals.prune(before_ts=time.time() - float(self.phases.domains.retention_seconds))
        await self.persistence.flush(self.channels.client)
        self.persistence.persist("cycle")
        return frame
