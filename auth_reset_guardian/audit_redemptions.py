# Copyright (c) 2026 PitchAI. All rights reserved.
"""Persist and recover guardian redemption attempts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack
from uuid import uuid4

from .audit_runs import RunAuditStore
from .audit_types import (
    PendingAttempt,
    RedemptionAttempt,
    encode_json,
    optional_int,
    optional_text,
    required_text,
    select_connection,
)
from .models import utc_iso

if TYPE_CHECKING:
    from datetime import datetime

    from .audit_types import (
        AttemptStartOptions,
        AttemptUpdateOptions,
    )


class RedemptionAuditStore(RunAuditStore):
    """Persist idempotent redemption attempts and reconciliation state."""

    def start_or_resume_attempt(
        self,
        *,
        run_id: str,
        **request: Unpack[AttemptStartOptions],
    ) -> RedemptionAttempt:
        """Start a redemption attempt or resume its unfinished predecessor.

        Returns:
            The resulting value.

        Raises:
            ValueError: If a value violates the required contract.

        """
        credit = request["credit"]
        observation = request["observation"]
        expires_at = credit.expires_at
        if expires_at is None:
            msg = "redemption attempts require an expiring credit"
            raise ValueError(msg)
        row = (
            select_connection(self._connection)
            .execute(
                """
            SELECT attempt_id, idempotency_key
              FROM redemption_attempts
             WHERE account_ref = ? AND credit_ref = ? AND expires_at = ?
               AND status IN ('started', 'uncertain')
             ORDER BY started_at ASC LIMIT 1
            """,
                (
                    observation.descriptor.account_ref,
                    credit.credit_ref,
                    utc_iso(expires_at),
                ),
            )
            .fetchone()
        )
        if row is not None:
            attempt_id = required_text(row, "attempt_id")
            with self._connection:
                _ = self._connection.execute(
                    """
                    UPDATE redemption_attempts
                       SET run_id = ?, updated_at = ?
                     WHERE attempt_id = ?
                    """,
                    (run_id, utc_iso(request["now"]), attempt_id),
                )
            return RedemptionAttempt(
                attempt_id=attempt_id,
                idempotency_key=required_text(row, "idempotency_key"),
                resumed=True,
            )
        return self._insert_attempt(run_id=run_id, expires_at=expires_at, **request)

    def _insert_attempt(
        self,
        *,
        run_id: str,
        expires_at: datetime,
        **request: Unpack[AttemptStartOptions],
    ) -> RedemptionAttempt:
        credit = request["credit"]
        observation = request["observation"]
        attempt_id = uuid4().hex
        idempotency_key = f"pitchai-reset-guardian:{credit.credit_ref[:20]}:{attempt_id}"
        with self._connection:
            _ = self._connection.execute(
                """
                INSERT INTO redemption_attempts(
                    attempt_id, idempotency_key, run_id, account_ref, account_label,
                    credit_ref, expires_at, reason, started_at, updated_at, status, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'started', '{}')
                """,
                (
                    attempt_id,
                    idempotency_key,
                    run_id,
                    observation.descriptor.account_ref,
                    observation.descriptor.label,
                    credit.credit_ref,
                    utc_iso(expires_at),
                    request["reason"],
                    utc_iso(request["now"]),
                    utc_iso(request["now"]),
                ),
            )
        return RedemptionAttempt(
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            resumed=False,
        )

    def update_attempt(
        self,
        *,
        attempt_id: str,
        now: datetime,
        status: str,
        **options: Unpack[AttemptUpdateOptions],
    ) -> None:
        """Persist one redemption-attempt state transition."""
        with self._connection:
            _ = self._connection.execute(
                """
                UPDATE redemption_attempts
                   SET updated_at = ?, status = ?, outcome = ?, windows_reset = ?,
                       verification = ?, error_code = ?, details_json = ?
                 WHERE attempt_id = ?
                """,
                (
                    utc_iso(now),
                    status,
                    options.get("outcome"),
                    options.get("windows_reset"),
                    options.get("verification"),
                    options.get("error_code"),
                    encode_json(options.get("details") or {}),
                    attempt_id,
                ),
            )

    def pending_attempts_for_account(self, *, account_ref: str) -> list[PendingAttempt]:
        """Load every unfinished redemption for one account.

        Returns:
            The resulting collection.

        """
        rows = (
            select_connection(self._connection)
            .execute(
                """
            SELECT attempt_id, credit_ref, expires_at, status, outcome, windows_reset
              FROM redemption_attempts
             WHERE account_ref = ?
               AND status IN ('started', 'uncertain', 'verification_failed')
             ORDER BY started_at ASC
            """,
                (account_ref,),
            )
            .fetchall()
        )
        attempts: list[PendingAttempt] = [
            PendingAttempt(
                attempt_id=required_text(row, "attempt_id"),
                credit_ref=required_text(row, "credit_ref"),
                expires_at=required_text(row, "expires_at"),
                status=required_text(row, "status"),
                outcome=optional_text(row, "outcome"),
                windows_reset=optional_int(row, "windows_reset"),
            )
            for row in rows
        ]
        return attempts
