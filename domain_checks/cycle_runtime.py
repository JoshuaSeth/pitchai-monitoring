# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bind prepared phase objects to the current client, browser and mutable records."""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from .browser_admission import BrowserAdmission, BrowserConnection
from .browser_recovery_phase import BrowserRecoveryPhase
from .cycle_assembly import PhaseAssembly
from .cycle_channels import CycleChannels
from .cycle_domain_phase import CycleDomainPhase, CycleInventory
from .cycle_iteration import CycleIteration
from .cycle_phases import BrowserPhases, CyclePhases
from .cycle_runner import CycleRunner
from .dispatch_records import DispatchRecords
from .domain_polling import DomainPolling
from .signal_history import SignalHistory
from .state_storage import write_state_atomic

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from httpx import AsyncClient

    from .common_check import DomainCheckResult
    from .cycle_assembly import NativeProbes, ObservationPhases
    from .cycle_preparation import CyclePreparation, CycleResources
    from .domain_polling import DomainCheckCall


@dataclass(frozen=True)
class BrowserOperations[BrowserT: BrowserConnection]:
    """Native callbacks keep their original launch, memory and observation contracts."""

    launch: Callable[[], Awaitable[BrowserT]]
    memory: Callable[[], Mapping[str, int]]
    hint: Callable[[], str]
    check: Callable[[DomainCheckCall[BrowserT]], Awaitable[DomainCheckResult]]


@dataclass(frozen=True)
class CycleRuntime[BrowserT: BrowserConnection]:
    """Shared references for startup persistence and the browser-bound cycle."""

    prepared: CyclePreparation
    resources: CycleResources
    channels: CycleChannels
    observations: ObservationPhases[BrowserT]
    signals: SignalHistory

    @staticmethod
    def bind[NativeBrowserT: BrowserConnection](
        prepared: CyclePreparation, resources: CycleResources,
        client: AsyncClient, probes: NativeProbes[NativeBrowserT],
    ) -> CycleRuntime[NativeBrowserT]:
        """Return phases bound to the existing objects without performing observations."""
        persistence = resources.persistence
        signals = SignalHistory(persistence.records.signals)
        activity = persistence.records.activity
        channels = CycleChannels(client, prepared.channels.telegram, prepared.channels.dispatch,
                                 prepared.channels.dispatch_state,
                                 DispatchRecords(activity.dispatch_history, activity.dispatch_last, activity.events),
                                 {})
        assembly = PhaseAssembly(prepared.settings, persistence, prepared.inventory.participants, signals)
        observations = assembly.build(channels, prepared.limits, prepared.inventory.specs, probes)
        return CycleRuntime(prepared, resources, channels, observations, signals)

    async def record_startup(self) -> None:
        """Preserve service-started enqueue, flush, then the loud direct state write."""
        persistence = self.resources.persistence
        if persistence.outbox is not None:
            persistence.event("service_started", time.time(), {
                "interval_seconds": int(self.prepared.limits.interval),
                "monitored_domains": self.prepared.browser.monitored,
            })
            await persistence.flush(self.channels.client)
            if persistence.path is not None:
                write_state_atomic(persistence.path, persistence.snapshot())

    def browser_runner(self, operations: BrowserOperations[BrowserT]) -> CycleRunner[BrowserT]:
        """Return the original browser/domain phases sharing current health and cleanup ownership."""
        persistence = self.resources.persistence
        admission = BrowserAdmission(persistence.browser, operations.launch, operations.memory)
        recovery = BrowserRecoveryPhase(admission, operations.hint, partial(persistence.persist, "browser_notice"))
        polling = DomainPolling(self.resources.checks, self.resources.browsers, self.channels.client,
                                admission, operations.check)
        inventory = CycleInventory(self.prepared.inventory.entries, self.prepared.inventory.specs,
                                   self.prepared.heartbeat.schedule.timezone)
        domain_cycle = CycleDomainPhase(inventory, persistence, admission, polling, self.observations.domains,
                                       self.prepared.settings.metrics.retention_seconds)
        phases = CyclePhases(domain_cycle, self.observations.history, self.observations.metrics,
                             BrowserPhases(self.observations.synthetic, self.observations.vitals, recovery),
                             self.prepared.heartbeat, self.observations.meta)
        iteration = CycleIteration(self.prepared.inventory.participants, self.channels, persistence,
                                   phases, self.signals)
        return CycleRunner(iteration, self.prepared.limits)
