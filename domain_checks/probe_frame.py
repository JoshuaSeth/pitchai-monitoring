# Copyright (c) 2026 PitchAI. All rights reserved.
"""Current domain selection and effects for scheduled monitoring observations."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .common_check import DomainCheckSpec
    from .cycle_channels import CycleChannels
    from .history_phase_context import EventSink
    from .signal_history import SignalHistory

LOGGER = logging.getLogger("service-monitoring")


class DomainObservation(Protocol):
    """The shared public result fields used by TLS and DNS routing."""

    @property
    def domain(self) -> str:
        """Domain whose monitoring policy applies to this observation.

        Raises:
            NotImplementedError: A concrete observation supplies this property.
        """
        raise NotImplementedError

    @property
    def ok(self) -> bool:
        """Whether this observation satisfies its existing check contract.

        Raises:
            NotImplementedError: A concrete observation supplies this property.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class ProbeDomains:
    """Preserve enabled order, known inventory and independently alertable set."""

    specs: list[DomainCheckSpec]
    known: set[str]
    alertable: set[str]

    def select[T: DomainObservation](self, results: list[T], label: str) -> list[T]:
        """Filter routing while retaining all results for heartbeat consumers.

        Returns:
            Alertable or unknown-domain results in their original order.
        """
        failed = [result for result in results if not result.ok]
        known_failed = [result for result in failed if result.domain in self.known]
        muted_results = [result for result in known_failed if result.domain not in self.alertable]
        muted = [result.domain for result in muted_results]
        suppressed = sorted(set(muted))
        if suppressed:
            LOGGER.info("%s failures excluded from Telegram routing domains=%s", label, suppressed)
        unknown = self.known - self.alertable
        return [result for result in results if result.domain not in unknown]


@dataclass(frozen=True)
class ProbeFrame:
    """One cycle's time, domain selection and existing effect references."""

    started: float
    domains: ProbeDomains
    channels: CycleChannels
    event: EventSink
    signals: SignalHistory


@dataclass
class ProbeSchedule:
    """Persist the last attempted observation before entering its await."""

    last_run_ts: float = 0.0

    def claim(self, *, enabled: bool, has_specs: bool, interval_minutes: int) -> bool:
        """Apply the original interval, including disabled and empty inventories.

        Returns:
            True when the timestamp was advanced for an observation attempt.
        """
        if not enabled:
            return False
        now = time.time()
        due = now - float(self.last_run_ts or 0.0) >= float(interval_minutes * 60)
        if not due or not has_specs:
            return False
        self.last_run_ts = now
        return True
