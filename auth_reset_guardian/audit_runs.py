# Copyright (c) 2026 PitchAI. All rights reserved.
"""Persist guardian run, snapshot, event, and warning records."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack
from uuid import uuid4

from .audit_schema import AuditConnection
from .audit_types import encode_json, summary_count
from .models import utc_iso

if TYPE_CHECKING:
    from datetime import datetime

    from .audit_types import EventOptions, WarningClaimOptions
    from .json_contract import JsonObject
    from .models import AccountObservation


class RunAuditStore(AuditConnection):
    """Persist the lifecycle and observations of guardian runs."""

    def start_run(self, *, mode: str, now: datetime) -> str:
        """Start one durable guardian run.

        Returns:
            The resulting text.

        """
        run_id = uuid4().hex
        with self._connection:
            _ = self._connection.execute(
                """
                INSERT INTO runs(run_id, mode, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (run_id, mode, utc_iso(now)),
            )
        return run_id

    def finish_run(
        self,
        *,
        run_id: str,
        now: datetime,
        status: str,
        summary: JsonObject,
    ) -> None:
        """Persist the terminal status and counters of one run."""
        with self._connection:
            _ = self._connection.execute(
                """
                UPDATE runs
                   SET completed_at = ?, status = ?, account_count = ?, credit_count = ?,
                       warning_count = ?, redemption_count = ?, error_count = ?, summary_json = ?
                 WHERE run_id = ?
                """,
                (
                    utc_iso(now),
                    status,
                    summary_count(summary, "account_count"),
                    summary_count(summary, "credit_count"),
                    summary_count(summary, "warning_count"),
                    summary_count(summary, "redemption_count"),
                    summary_count(summary, "error_count"),
                    encode_json(summary),
                    run_id,
                ),
            )

    def record_snapshot(
        self,
        *,
        run_id: str,
        phase: str,
        observation: AccountObservation,
    ) -> None:
        """Persist one sanitized account observation."""
        sanitized = observation.sanitized()
        with self._connection:
            _ = self._connection.execute(
                """
                INSERT INTO snapshots(
                    run_id, captured_at, phase, account_ref, account_label, state_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_iso(observation.captured_at),
                    phase,
                    observation.descriptor.account_ref,
                    observation.descriptor.label,
                    encode_json(sanitized),
                ),
            )

    def record_event(
        self,
        *,
        run_id: str,
        now: datetime,
        event_type: str,
        **options: Unpack[EventOptions],
    ) -> None:
        """Persist one sanitized audit event."""
        expires_at = options.get("expires_at")
        with self._connection:
            _ = self._connection.execute(
                """
                INSERT INTO events(
                    run_id, occurred_at, event_type, severity, account_ref, account_label,
                    credit_ref, expires_at, threshold_hours, attempt_id, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_iso(now),
                    event_type,
                    options.get("severity", "info"),
                    options.get("account_ref"),
                    options.get("account_label"),
                    options.get("credit_ref"),
                    utc_iso(expires_at) if expires_at else None,
                    options.get("threshold_hours"),
                    options.get("attempt_id"),
                    encode_json(options.get("details") or {}),
                ),
            )

    def claim_warning(
        self,
        *,
        run_id: str,
        **claim: Unpack[WarningClaimOptions],
    ) -> bool:
        """Claim one warning threshold exactly once.

        Returns:
            Whether the operation satisfied its contract.

        Raises:
            ValueError: If a value violates the required contract.

        """
        credit = claim["credit"]
        expires_at = credit.expires_at
        if expires_at is None:
            msg = "warning claims require an expiring credit"
            raise ValueError(msg)
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO warning_marks(
                    mode, account_ref, credit_ref, expires_at, threshold_hours,
                    first_run_id, first_observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim["mode"],
                    claim["account_ref"],
                    credit.credit_ref,
                    utc_iso(expires_at),
                    claim["threshold_hours"],
                    run_id,
                    utc_iso(claim["now"]),
                ),
            )
        return cursor.rowcount == 1
