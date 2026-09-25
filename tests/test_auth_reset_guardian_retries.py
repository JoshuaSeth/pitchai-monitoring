# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian retry, ambiguity, and audit-redaction behavior."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, override

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.audit_types import select_connection
from auth_reset_guardian.clients import (
    RemoteCallError,
    SimulationSource,
)
from auth_reset_guardian.guardian import Guardian
from domain_checks.testing import verify
from tests.auth_reset_guardian_sql_support import (
    required_row,
    row_int,
    row_text,
)
from tests.auth_reset_guardian_support import (
    UTC,
    MutableClock,
    append_consume_outcome,
    guardian_fixture,
    required_array,
    required_array_object,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from auth_reset_guardian.json_contract import JsonObject
    from auth_reset_guardian.models import (
        AccountObservation,
        ConsumeResult,
        ResetCredit,
    )

EXPECTED_MULTI_ACCOUNT_COUNT = 2
EXPECTED_RETRY_CONSUME_CALL_COUNT = 2


def test_nothing_to_reset_is_retried_with_a_new_logical_idempotency_key(
    tmp_path: Path,
) -> None:
    """Retry a non-terminal result with a fresh logical idempotency key."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    clock = MutableClock(now)
    fixture = guardian_fixture(
        expires_at=now + timedelta(hours=1),
        outcome="nothing_to_reset",
    )
    append_consume_outcome(
        fixture,
        provider_id="opaque-provider-credit",
        outcome={"code": "nothing_to_reset", "windows_reset": 0},
    )
    source = SimulationSource(fixture, clock=clock)

    messages: list[str] = []

    def record_notification(message: str) -> None:
        messages.append(message)

    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        first = Guardian(
            source=source,
            audit=audit,
            notifier=record_notification,
            clock=clock,
        ).run(mode="simulation", dry_run=False)
    clock.advance(timedelta(minutes=15))
    with AuditStore(db_path) as audit:
        second = Guardian(
            source=source,
            audit=audit,
            notifier=record_notification,
            clock=clock,
        ).run(mode="simulation", dry_run=False)
    verify(first.redemption_attempt_count == second.redemption_attempt_count == 1)
    verify(len(source.consume_calls) == EXPECTED_RETRY_CONSUME_CALL_COUNT)
    verify(source.consume_calls[0]["idempotency_key"] != source.consume_calls[1]["idempotency_key"])
    verify(len(messages) == 1)
    verify("nothing_to_reset" in messages[0])
    verify("Automatic retries continue every 15 minutes" in messages[0])
    with sqlite3.connect(db_path) as connection:
        notification_query = (
            "SELECT status, attempts FROM notifications WHERE notification_key LIKE 'redemption-waiting:%'"
        )
        row = required_row(select_connection(connection).execute(notification_query))
    verify(row_text(row, 0) == "sent")
    verify(row_int(row, 1) == 1)


def test_same_credit_id_and_expiry_do_not_resume_another_accounts_attempt(
    tmp_path: Path,
) -> None:
    """Keep ambiguous attempts isolated even when provider credit IDs match."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    fixture = guardian_fixture(
        expires_at=now + timedelta(hours=1),
        credit_id="shared-provider-id",
        outcome="reset",
    )
    accounts = required_array(fixture, "accounts")
    second = deepcopy(required_array_object(accounts, 0))
    second["label"] = "support@pitchai.net"
    accounts.append(second)

    class FirstAccountAmbiguousSource(SimulationSource):
        """Return an ambiguous transport outcome for only the first account."""

        @override
        def consume_credit(
            self,
            observation: AccountObservation,
            credit: ResetCredit,
            idempotency_key: str,
        ) -> ConsumeResult:
            """Record and fail the first account, then delegate all others.

            Returns:
                The resulting value.

            Raises:
                RemoteCallError: If the remote boundary call fails.

            """
            if observation.descriptor.label == "info@pitchai.net":
                captured_call: dict[str, str] = {
                    "account_ref": observation.descriptor.account_ref,
                    "credit_ref": credit.credit_ref,
                    "provider_id": credit.provider_id,
                    "idempotency_key": idempotency_key,
                }
                self.consume_calls.append(captured_call)
                raise RemoteCallError(
                    endpoint="provider_consume_reset_credit",
                    error_code="transport_timeout",
                    ambiguous=True,
                )
            return super().consume_credit(observation, credit, idempotency_key)

    source = FirstAccountAmbiguousSource(fixture, clock=lambda: now)
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation",
            dry_run=False,
        )

    verify(summary.redemption_attempt_count == EXPECTED_MULTI_ACCOUNT_COUNT)
    verify(summary.redemption_count == 1)
    verify(summary.error_count == 1)
    verify(len(source.consume_calls) == EXPECTED_MULTI_ACCOUNT_COUNT)
    account_refs = {call["account_ref"] for call in source.consume_calls}
    idempotency_keys = {
        call["idempotency_key"] for call in source.consume_calls
    }
    verify(
        len(account_refs) == EXPECTED_MULTI_ACCOUNT_COUNT,
    )
    verify(
        len(idempotency_keys) == EXPECTED_MULTI_ACCOUNT_COUNT,
    )
    with sqlite3.connect(db_path) as connection:
        rows = (
            select_connection(connection)
            .execute("SELECT account_ref, idempotency_key FROM redemption_attempts")
            .fetchall()
        )
    verify(len(rows) == EXPECTED_MULTI_ACCOUNT_COUNT)
    account_refs: set[str] = set()
    idempotency_keys: set[str] = set()
    for row in rows:
        account_refs.add(row_text(row, 0))
        idempotency_keys.add(row_text(row, 1))
    verify(len(account_refs) == EXPECTED_MULTI_ACCOUNT_COUNT)
    verify(len(idempotency_keys) == EXPECTED_MULTI_ACCOUNT_COUNT)


def test_ambiguous_attempt_resumes_the_same_idempotency_key(tmp_path: Path) -> None:
    """Resume an ambiguous attempt with its original idempotency key."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    clock = MutableClock(now)

    class AmbiguousThenSuccessSource(SimulationSource):
        """Fail the first consume ambiguously and succeed on the retry."""

        def __init__(
            self,
            fixture: JsonObject,
            *,
            clock: Callable[[], datetime] | None = None,
        ) -> None:
            """Initialize the deterministic source and observed key list."""
            super().__init__(fixture, clock=clock)
            self.keys: list[str] = []

        @override
        def consume_credit(
            self,
            observation: AccountObservation,
            credit: ResetCredit,
            idempotency_key: str,
        ) -> ConsumeResult:
            """Capture the key, then fail the first consume ambiguously.

            Returns:
                The resulting value.

            Raises:
                RemoteCallError: If the remote boundary call fails.

            """
            self.keys.append(idempotency_key)
            if len(self.keys) == 1:
                raise RemoteCallError(
                    endpoint="provider_consume_reset_credit",
                    error_code="transport_timeout",
                    ambiguous=True,
                )
            return super().consume_credit(observation, credit, idempotency_key)

    source = AmbiguousThenSuccessSource(
        guardian_fixture(expires_at=now + timedelta(hours=1), outcome="reset"),
        clock=clock,
    )
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        first = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation",
            dry_run=False,
        )
    clock.advance(timedelta(minutes=15))
    with AuditStore(db_path) as audit:
        second = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation",
            dry_run=False,
        )
    verify(first.error_count == 1)
    verify(second.redemption_count == 1)
    verify(source.keys[0] == source.keys[1])
