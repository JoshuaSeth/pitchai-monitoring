# Copyright (c) 2026 PitchAI. All rights reserved.
"""Filter recorded-history alerts and advance their independent health state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .alert_settings import AlertSettings
    from .health_state import HealthState
    from .history_phase_context import HistoryFrame
    from .metrics_red import RedViolation
    from .metrics_slo import SloBurnViolation

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class HistoryObservation[ViolationT: (SloBurnViolation, RedViolation)]:
    """Retain filtered results and the previous effective health for recovery."""

    violations: list[ViolationT]
    previous: bool
    alerted_down: bool


@dataclass(frozen=True)
class HistoryHealth:
    """References to one family's health, policy and current cycle observation."""

    name: str
    state: HealthState
    settings: AlertSettings
    frame: HistoryFrame
    excluded_log: str

    def observe[ViolationT: (SloBurnViolation, RedViolation)](
        self, violations: list[ViolationT],
    ) -> HistoryObservation[ViolationT]:
        """Keep dashboard-only domains out of routing and preserve sample order.

        Returns:
            The routed violations and transition evidence for the owning phase.
        """
        suppressed = sorted({value.domain for value in violations if value.domain not in self.frame.alertable})
        if suppressed:
            LOGGER.info(self.excluded_log, suppressed)
        routed = [value for value in violations if value.domain in self.frame.alertable]
        previous = bool(self.state.last_ok)
        alerted_down = self.state.advance(observed_ok=not bool(routed), thresholds=self.settings)
        self.frame.signals.append(
            self.name, [float(self.frame.started), 1 if bool(self.state.last_ok) else 0, len(routed)],
        )
        return HistoryObservation(routed, previous, alerted_down)
