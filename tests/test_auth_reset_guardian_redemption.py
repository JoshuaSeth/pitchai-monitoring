# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian fresh-recheck and exact-credit redemption behavior."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, override

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.clients import SimulationSource
from auth_reset_guardian.guardian import Guardian
from auth_reset_guardian.models import (
    utc_iso,
)
from domain_checks.testing import verify
from tests.auth_reset_guardian_event_support import read_events
from tests.auth_reset_guardian_support import (
    UTC,
    MutableClock,
    credit_fixture,
    guardian_fixture,
    required_array,
    required_array_object,
    required_object,
)

if TYPE_CHECKING:
    from pathlib import Path

    from auth_reset_guardian.json_contract import JsonObject
    from auth_reset_guardian.models import (
        AccountDescriptor,
        AccountObservation,
    )

EXPECTED_DRY_RUN_REFRESH_COUNT = 2
EXPECTED_REDEMPTION_REFRESH_COUNT = 3
EXPECTED_REDEMPTION_WARNING_COUNT = 4


def test_simulation_redeems_exact_credit_after_fresh_recheck(tmp_path: Path) -> None:
    """Redeem only the exact credit selected before the fresh recheck."""
    now = datetime(2026, 8, 11, 19, 45, tzinfo=UTC)
    expiry = now + timedelta(minutes=83)
    clock = MutableClock(now)
    source = SimulationSource(
        guardian_fixture(
            expires_at=expiry,
            credit_id="exact-credit-a",
            outcome="reset",
        ),
        clock=clock,
    )
    with AuditStore(tmp_path / "audit.sqlite3") as audit:
        summary = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation",
            dry_run=False,
        )

    verify(summary.warning_count == EXPECTED_REDEMPTION_WARNING_COUNT)
    verify(summary.redemption_attempt_count == 1)
    verify(summary.redemption_count == 1)
    verify(summary.error_count == 0)
    verify(len(source.consume_calls) == 1)
    verify(source.consume_calls[0]["provider_id"] == "exact-credit-a")
    verify(source.refresh_calls[next(iter(source.refresh_calls))] == EXPECTED_REDEMPTION_REFRESH_COUNT)


def test_live_style_dry_run_performs_fresh_recheck_but_never_consumes(
    tmp_path: Path,
) -> None:
    """Perform the fresh recheck in dry-run mode without consuming a credit."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    clock = MutableClock(now)
    source = SimulationSource(
        guardian_fixture(expires_at=now + timedelta(hours=1)),
        clock=clock,
    )
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=clock).run(
            mode="dry_run",
            dry_run=True,
        )
    verify(summary.redemption_attempt_count == 0)
    verify(not source.consume_calls)
    verify(next(iter(source.refresh_calls.values())) == EXPECTED_DRY_RUN_REFRESH_COUNT)
    suppressed = False
    for event in read_events(db_path):
        if event.get("event_type") == "redemption_suppressed_dry_run":
            suppressed = True
    verify(suppressed)


def test_credit_removed_between_inventory_and_recheck_is_not_replaced_by_another_credit(
    tmp_path: Path,
) -> None:
    """Never substitute a later credit when the selected credit disappears."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    expiry = now + timedelta(hours=1)

    class RacingSource(SimulationSource):
        """Remove the selected credit immediately after the initial refresh."""

        @override
        def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
            """Refresh once, then arrange for the selected credit to disappear.

            Returns:
                The resulting value.

            """
            observation = super().refresh_account(descriptor)
            if self.refresh_calls[descriptor.account_ref] == 1:
                self.remove_credit_before_next_refresh(
                    label="info@pitchai.net",
                    provider_id="earliest-credit",
                )
            return observation

    fixture = guardian_fixture(
        expires_at=expiry,
        credit_id="earliest-credit",
        outcome="reset",
    )
    accounts = required_array(fixture, "accounts")
    account = required_array_object(accounts, 0)
    inventory = required_object(account, "credit_inventory")
    inventory_credits = required_array(inventory, "credits")
    inventory_credits.append(
        credit_fixture(credit_id="later-credit", expires_at=now + timedelta(days=1)),
    )
    inventory["available_count"] = 2
    source = RacingSource(fixture, clock=lambda: now)
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation",
            dry_run=False,
        )
    verify(summary.redemption_attempt_count == 0)
    verify(not source.consume_calls)
    skipped = False
    for event in read_events(db_path):
        if event.get("event_type") == "redemption_skipped_after_fresh_recheck":
            skipped = True
    verify(skipped)


def test_same_credit_id_with_changed_expiry_fails_loudly_without_consuming(
    tmp_path: Path,
) -> None:
    """Fail loudly when a provider reuses the credit ID with another expiry."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    selected_expiry = now + timedelta(hours=1)
    changed_expiry = selected_expiry + timedelta(minutes=15)

    class ExpiryChangedSource(SimulationSource):
        """Change the selected credit expiry after its initial observation."""

        @override
        def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
            """Refresh once, then mutate the fixture's exact credit expiry.

            Returns:
                The resulting value.

            """
            observation = super().refresh_account(descriptor)
            if self.refresh_calls[descriptor.account_ref] == 1:
                account = self._find(descriptor)
                inventory = required_object(account, "credit_inventory")
                inventory_credits = required_array(inventory, "credits")
                exact_credit = required_array_object(inventory_credits, 0)
                exact_credit["expires_at"] = utc_iso(changed_expiry)
            return observation

    source = ExpiryChangedSource(
        guardian_fixture(
            expires_at=selected_expiry,
            credit_id="same-opaque-credit",
            outcome="reset",
        ),
        clock=lambda: now,
    )
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation",
            dry_run=False,
        )

    verify(summary.redemption_attempt_count == 0)
    verify(summary.redemption_count == 0)
    verify(summary.error_count == 1)
    verify(not source.consume_calls)
    events = read_events(db_path)
    mismatch_events: list[JsonObject] = [
        event
        for event in events
        if event.get("event_type") == "redemption_skipped_expiry_mismatch"
    ]
    verify(len(mismatch_events) == 1)
    verify(mismatch_events[0]["severity"] == "error")
