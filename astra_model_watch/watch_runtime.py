# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runtime dependencies and aggregate counters for the ASTRA watch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .catalog import CatalogClient
from .schedule import WatchRuntime
from .watch_summary import WatchCoverage, WatchOutcome, WatchSummary, WatchWindow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .notifier import Notifier
    from .types import AccountCheck, CycleSummary, WatchConfig


@dataclass(frozen=True)
class WatchDependencies:
    """Replaceable catalog, notification, and clock dependencies."""

    catalog_client: CatalogClient = field(default_factory=CatalogClient)
    notifier: Notifier | None = None
    runtime: WatchRuntime = field(default_factory=WatchRuntime)


@dataclass
class WatchCounters:
    """Mutable aggregate counters for one finite process."""

    account_observations: int = 0
    account_checks: int = 0
    unavailable_observations: int = 0
    provider_requests: int = 0
    errors: int = 0
    matches: int = 0
    alerts: int = 0

    def record(
        self,
        cycle: CycleSummary,
        checks: Sequence[AccountCheck],
        sent: int,
        notification_errors: int,
    ) -> None:
        """Accumulate one completed cycle."""
        self.account_observations += len(checks)
        self.account_checks += cycle.checked_count
        self.unavailable_observations += cycle.unavailable_count
        for check in checks:
            self.provider_requests += check.provider_request_count
        self.errors += cycle.error_count + notification_errors
        self.matches += cycle.match_count
        self.alerts += sent


@dataclass(frozen=True)
class CycleMeasurements:
    """Per-cycle counts derived from sanitized account outcomes."""

    checked: int
    unavailable: int
    errors: int
    matches: int
    provider_requests: int

    @classmethod
    def from_checks(cls, checks: Sequence[AccountCheck]) -> CycleMeasurements:
        """Count successful checks, failures, matches, and provider requests.

        Returns:
            Aggregated measurements for one cycle.
        """
        checked = 0
        unavailable = 0
        errors = 0
        matches = 0
        provider_requests = 0
        for check in checks:
            if check.unavailable_reason is not None:
                unavailable += 1
            elif check.error_code is None:
                checked += 1
            else:
                errors += 1
            matches += len(check.matches)
            provider_requests += check.provider_request_count
        return cls(checked, unavailable, errors, matches, provider_requests)


@dataclass(frozen=True)
class WatchBounds:
    """Timing and inventory bounds used to validate completion."""

    started_at_utc: str
    completed_at_utc: str
    elapsed_seconds: float
    expected_cycles: int
    baseline_count: int


def build_watch_summary(
    config: WatchConfig,
    cycles: Sequence[CycleSummary],
    counters: WatchCounters,
    bounds: WatchBounds,
) -> WatchSummary:
    """Evaluate every completion invariant and build flattened evidence."""
    inventory_stable = True
    account_counts_complete = True
    account_outcomes_complete = True
    usable_accounts_present = True
    schedule_on_time = True
    for cycle in cycles:
        inventory_stable = inventory_stable and not cycle.inventory_changed
        account_counts_complete = (
            account_counts_complete and cycle.account_count == bounds.baseline_count
        )
        account_outcomes_complete = account_outcomes_complete and (
            cycle.checked_count + cycle.unavailable_count == bounds.baseline_count
        )
        usable_accounts_present = usable_accounts_present and cycle.checked_count > 0
        schedule_on_time = (
            schedule_on_time
            and cycle.start_lateness_seconds <= config.max_start_lateness_seconds
        )
    validity_checks = (
        bounds.elapsed_seconds >= config.duration_seconds,
        len(cycles) == bounds.expected_cycles,
        bounds.baseline_count > 0,
        counters.errors == 0,
        inventory_stable,
        account_counts_complete,
        account_outcomes_complete,
        usable_accounts_present,
        schedule_on_time,
    )
    valid = all(validity_checks)
    return WatchSummary(
        window=WatchWindow(
            bounds.started_at_utc,
            bounds.completed_at_utc,
            round(bounds.elapsed_seconds, 3),
        ),
        coverage=WatchCoverage(
            cycle_count=len(cycles),
            expected_cycle_count=bounds.expected_cycles,
            baseline_account_count=bounds.baseline_count,
            account_observation_count=counters.account_observations,
            account_check_count=counters.account_checks,
            unavailable_observation_count=counters.unavailable_observations,
            provider_request_count=counters.provider_requests,
        ),
        outcome=WatchOutcome(
            counters.errors,
            counters.matches,
            counters.alerts,
            valid,
        ),
    )
