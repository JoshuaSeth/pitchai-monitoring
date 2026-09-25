# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scheduled ASTRA catalog watch and evidence recording."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from .alerts import MatchAlerter
from .audit import AlertState, AuditLog
from .checks import check_account
from .evidence import account_check_event, safety_evidence
from .inventory import InventoryError, load_broker_accounts
from .json_types import JsonObject
from .schedule import wait_until
from .types import (
    AccountCheck,
    BrokerAccount,
    CycleAccountCoverage,
    CycleSummary,
    CycleTiming,
    WatchConfig,
)
from .watch_runtime import (
    CycleMeasurements,
    WatchBounds,
    WatchCounters,
    WatchDependencies,
    build_watch_summary,
)

if TYPE_CHECKING:
    from .watch_summary import WatchSummary


@final
class AstraModelWatch:
    """Poll all broker accounts and immediately alert on new ASTRA matches."""

    def __init__(
        self,
        *,
        config: WatchConfig,
        audit: AuditLog,
        alert_state: AlertState,
        dependencies: WatchDependencies | None = None,
    ) -> None:
        resolved = dependencies or WatchDependencies()
        self.config = config
        self.audit = audit
        self.catalog_client = resolved.catalog_client
        self.runtime = resolved.runtime
        self._baseline_inventory: tuple[str, ...] | None = None
        self.alerter = MatchAlerter(
            audit=audit,
            alert_state=alert_state,
            notifier=resolved.notifier,
            wall_clock=resolved.runtime.wall_clock,
        )

    def _log(
        self,
        event: JsonObject,
        accounts: list[BrokerAccount] | None = None,
    ) -> None:
        sensitive: list[str] = []
        for account in accounts or []:
            sensitive.append(account.access_token or "")
        self.audit.append(event, sensitive_values=sensitive)

    def _record_account_check(self, cycle_index: int, check: AccountCheck) -> None:
        self._log(account_check_event(cycle_index, check), [check.account])

    def _run_cycle(
        self,
        cycle_index: int,
        scheduled_at: float,
    ) -> tuple[CycleSummary, list[AccountCheck]]:
        cycle_started_monotonic = self.runtime.monotonic()
        started_at = self.runtime.wall_clock()
        try:
            accounts = load_broker_accounts(self.config.accounts_dir)
        except InventoryError as exc:
            completed_at = self.runtime.wall_clock()
            self._log(
                {
                    "event_type": "account_inventory_failed",
                    "timestamp_utc": completed_at,
                    "cycle_index": cycle_index,
                    "error_code": exc.error_code,
                    "safety": safety_evidence(0),
                },
            )
            return (
                CycleSummary(
                    cycle_index=cycle_index,
                    coverage=CycleAccountCoverage(0, 0, 0),
                    error_count=1,
                    match_count=0,
                    inventory_changed=True,
                    timing=CycleTiming(
                        started_at,
                        completed_at,
                        max(0.0, cycle_started_monotonic - scheduled_at),
                    ),
                ),
                [],
            )
        inventory = tuple(account.fingerprint for account in accounts)
        if self._baseline_inventory is None:
            self._baseline_inventory = inventory
        inventory_changed = inventory != self._baseline_inventory
        checks: list[AccountCheck] = []
        for account in accounts:
            checks.append(
                check_account(
                    account,
                    catalog_client=self.catalog_client,
                    client_version=self.config.client_version,
                    timeout_seconds=self.config.request_timeout_seconds,
                    wall_clock=self.runtime.wall_clock,
                ),
            )
        for check in checks:
            self._record_account_check(cycle_index, check)
        measurements = CycleMeasurements.from_checks(checks)
        summary = CycleSummary(
            cycle_index=cycle_index,
            coverage=CycleAccountCoverage(
                len(accounts),
                measurements.checked,
                measurements.unavailable,
            ),
            error_count=measurements.errors,
            match_count=measurements.matches,
            inventory_changed=inventory_changed,
            timing=CycleTiming(
                started_at_utc=started_at,
                completed_at_utc=self.runtime.wall_clock(),
                start_lateness_seconds=max(0.0, cycle_started_monotonic - scheduled_at),
            ),
        )
        self._log(
            {
                "event_type": "catalog_cycle_completed",
                "timestamp_utc": summary.completed_at_utc,
                **summary.audit_fields(),
                "safety": safety_evidence(measurements.provider_requests),
            },
            accounts,
        )
        return summary, checks

    def preflight(self) -> None:
        """Validate timing and prove a configured notification route is private."""
        if self.config.interval_seconds <= 0 or self.config.duration_seconds < 0:
            raise ValueError(
                "watch timing must be non-negative with a positive interval",
            )
        if (
            self.config.heartbeat_seconds <= 0
            or self.config.request_timeout_seconds <= 0
        ):
            raise ValueError("heartbeat and request timeout must be positive")
        self.alerter.preflight()

    def run(self) -> WatchSummary:
        """Run every scheduled check, including the sample at the two-hour boundary."""
        self.preflight()
        started_at = self.runtime.wall_clock()
        started_monotonic = self.runtime.monotonic()
        expected_cycles = (
            int(self.config.duration_seconds // self.config.interval_seconds) + 1
        )
        self._log(
            {
                "event_type": "watch_started",
                "timestamp_utc": started_at,
                "accounts_dir": str(self.config.accounts_dir),
                "client_version": self.config.client_version,
                "interval_seconds": self.config.interval_seconds,
                "duration_seconds": self.config.duration_seconds,
                "expected_cycle_count": expected_cycles,
                "safety": safety_evidence(0),
            },
        )
        cycles: list[CycleSummary] = []
        counters = WatchCounters()
        for cycle_index in range(expected_cycles):
            scheduled_at = (
                started_monotonic + cycle_index * self.config.interval_seconds
            )
            wait_until(
                due=scheduled_at,
                cycle_index=cycle_index,
                heartbeat_seconds=self.config.heartbeat_seconds,
                runtime=self.runtime,
                record=self._log,
            )
            cycle, checks = self._run_cycle(cycle_index, scheduled_at)
            sent, notification_errors = self.alerter.notify_new_matches(checks)
            cycles.append(cycle)
            counters.record(cycle, checks, sent, notification_errors)
            print(
                " ".join(
                    (
                        f"CATALOG_CYCLE index={cycle_index}",
                        f"accounts={cycle.account_count}",
                        f"checked={cycle.checked_count}",
                        f"unavailable={cycle.unavailable_count}",
                        f"errors={cycle.error_count + notification_errors}",
                        f"astra_matches={cycle.match_count}",
                        f"alerts_sent={sent}",
                    )
                ),
                flush=True,
            )
        elapsed = self.runtime.monotonic() - started_monotonic
        completed_at = self.runtime.wall_clock()
        summary = build_watch_summary(
            self.config,
            cycles,
            counters,
            WatchBounds(
                started_at,
                completed_at,
                elapsed,
                expected_cycles,
                len(self._baseline_inventory or ()),
            ),
        )
        self._log(
            {
                "event_type": "watch_completed",
                "timestamp_utc": completed_at,
                **summary.audit_fields(),
                "safety": safety_evidence(counters.provider_requests),
            },
        )
        print(
            " ".join(
                (
                    f"WATCH_COMPLETE valid_window={str(summary.valid_window).lower()}",
                    f"elapsed_seconds={summary.elapsed_seconds}",
                    f"cycles={summary.cycle_count}/{expected_cycles}",
                    f"account_checks={counters.account_checks}",
                    f"unavailable_observations={counters.unavailable_observations}",
                    f"errors={counters.errors}",
                    f"astra_matches={counters.matches}",
                    f"alerts_sent={counters.alerts}",
                )
            ),
            flush=True,
        )
        return summary
