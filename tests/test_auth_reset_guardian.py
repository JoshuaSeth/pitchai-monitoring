# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian containment to declared external boundary failures."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, final, override

import pytest

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.clients import GuardianSource
from auth_reset_guardian.guardian import Guardian
from domain_checks.testing import verify
from tests.auth_reset_guardian_event_support import event_details, read_events
from tests.auth_reset_guardian_support import UTC

if TYPE_CHECKING:
    from pathlib import Path

    from auth_reset_guardian.json_contract import JsonObject
    from auth_reset_guardian.models import (
        AccountDescriptor,
        AccountObservation,
        ConsumeResult,
        ResetCredit,
    )


@final
class InventoryBoundarySource(GuardianSource):
    """Raise one configured exception from account inventory."""

    def __init__(self, error: Exception) -> None:
        """Store the inventory exception under test."""
        self.error = error

    @override
    def list_accounts(self) -> list[AccountDescriptor]:
        """Raise the configured inventory exception."""
        raise self.error

    @override
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        """Reject an unreachable account refresh.

        Raises:
            AssertionError: If the value violates the validation contract.

        """
        _ = descriptor
        msg = "inventory failure must stop account refresh"
        raise AssertionError(msg)

    @override
    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        """Reject an unreachable credit consumption.

        Raises:
            AssertionError: If the value violates the validation contract.

        """
        _ = observation, credit, idempotency_key
        msg = "inventory failure must stop credit consumption"
        raise AssertionError(msg)


@pytest.mark.parametrize(
    "source_error",
    [
        OSError("read failed"),
        RuntimeError("source unavailable"),
        ValueError("bad data"),
    ],
)
def test_declared_inventory_failures_finish_a_failed_run(
    tmp_path: Path,
    source_error: Exception,
) -> None:
    """Contain declared inventory failures and durably finish the run."""
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(
            source=InventoryBoundarySource(source_error),
            audit=audit,
            clock=lambda: now,
        ).run(mode="boundary_test", dry_run=True)

    verify(summary.status == "failed")
    verify(summary.error_count == 1)
    verify(summary.account_count == 0)
    events = read_events(db_path)
    inventory_events: list[JsonObject] = [
        event
        for event in events
        if event["event_type"] == "account_inventory_failed"
    ]
    verify(len(inventory_events) == 1)
    details = event_details(inventory_events[0])
    verify(details["error_code"] == f"unexpected:{type(source_error).__name__}")


def test_unexpected_inventory_defect_propagates(tmp_path: Path) -> None:
    """Fail loudly when inventory implementation code raises a programmer defect."""
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    with AuditStore(tmp_path / "audit.sqlite3") as audit:
        guardian = Guardian(
            source=InventoryBoundarySource(TypeError("programmer defect")),
            audit=audit,
            clock=lambda: now,
        )
        with pytest.raises(TypeError, match="programmer defect"):
            _ = guardian.run(mode="boundary_test", dry_run=True)
