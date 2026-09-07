# Copyright (c) 2026 PitchAI. All rights reserved.
"""SQLite coordination for one organization-wide reset redemption."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING, cast

from .models import parse_timestamp, utc_iso
from .organization_claim import CoordinatedAttempt, row_text
from .organization_claim_creation import insert_attempt

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from .organization_claim import ClaimRequest


CLAIM_LEASE = timedelta(minutes=10)
REATTEMPT_COOLDOWN = timedelta(minutes=10)
PERMANENT_STATES = ("succeeded", "reconciled_absent")


class OrganizationAttemptStore:
    """Additive coordination state beside the guardian's version-two audit schema."""

    def __init__(self, path: Path) -> None:
        """Open the shared audit database and ensure additive claim state exists."""
        self._connection: sqlite3.Connection = sqlite3.connect(path, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        _ = self._connection.execute("PRAGMA foreign_keys = ON")
        _ = self._connection.execute("PRAGMA journal_mode = WAL")
        _ = self._connection.execute("PRAGMA synchronous = FULL")
        _ = self._connection.execute("PRAGMA busy_timeout = 30000")
        self._initialize()

    def close(self) -> None:
        """Close the coordination connection."""
        self._connection.close()

    def _initialize(self) -> None:
        _ = self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS organization_redemption_claims (
                claim_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                decision_key TEXT NOT NULL,
                attempt_id TEXT NOT NULL UNIQUE REFERENCES redemption_attempts(attempt_id),
                account_ref TEXT NOT NULL,
                credit_ref TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                weekly_reset_at TEXT NOT NULL,
                state TEXT NOT NULL,
                lease_owner TEXT NOT NULL,
                lease_until TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS organization_one_active_claim_idx
                ON organization_redemption_claims(scope)
             WHERE state IN ('claimed', 'uncertain', 'verification_failed');
            CREATE INDEX IF NOT EXISTS organization_decision_history_idx
                ON organization_redemption_claims(decision_key, updated_at);
            """,
        )
        self._connection.commit()

    def reconcile_terminal_attempts(self) -> None:
        """Mirror terminal attempt states so a restart cannot leave a stale active claim."""
        statement = """
            UPDATE organization_redemption_claims
               SET state = (
                       SELECT status FROM redemption_attempts
                        WHERE attempt_id = organization_redemption_claims.attempt_id
                   ),
                   updated_at = (
                       SELECT updated_at FROM redemption_attempts
                        WHERE attempt_id = organization_redemption_claims.attempt_id
                   )
             WHERE state IN ('claimed', 'uncertain', 'verification_failed')
               AND (SELECT status FROM redemption_attempts
                     WHERE attempt_id = organization_redemption_claims.attempt_id)
                   NOT IN ('started', 'uncertain', 'verification_failed')
        """
        with self._connection:
            _ = self._connection.execute(statement)

    def claim(self, request: ClaimRequest) -> CoordinatedAttempt:
        """Atomically acquire, resume, or suppress the sole organization claim.

        Returns:
            The durable provider attempt and whether this run owns its lease.
        """
        _ = self._connection.execute("BEGIN IMMEDIATE")
        self._sync_terminal_attempts_in_transaction()
        active = cast(
            "sqlite3.Row | None",
            self._connection.execute(
                """
                SELECT claims.*, attempts.idempotency_key, attempts.status AS attempt_status
                  FROM organization_redemption_claims AS claims
                  JOIN redemption_attempts AS attempts USING (attempt_id)
                 WHERE claims.state IN ('claimed', 'uncertain', 'verification_failed')
                 ORDER BY claims.created_at LIMIT 1
                """,
            ).fetchone(),
        )
        if active is not None:
            attempt = self._resume_active(active, request)
            self._connection.commit()
            return attempt
        recent = cast(
            "sqlite3.Row | None",
            self._connection.execute(
                """
                SELECT claims.*, attempts.idempotency_key, attempts.status AS attempt_status
                  FROM organization_redemption_claims AS claims
                  JOIN redemption_attempts AS attempts USING (attempt_id)
                 WHERE claims.decision_key = ?
                 ORDER BY claims.created_at DESC LIMIT 1
                """,
                (request.decision_key,),
            ).fetchone(),
        )
        if recent is not None and self._terminal_suppresses(recent, request.now):
            attempt = self._suppressed_attempt(recent)
            self._connection.commit()
            return attempt
        attempt = insert_attempt(
            self._connection,
            request,
            lease_until=request.now + CLAIM_LEASE,
        )
        self._connection.commit()
        return attempt

    def mark(self, *, attempt_id: str, state: str, now: datetime) -> None:
        """Persist the coordination state corresponding to an attempt update."""
        with self._connection:
            _ = self._connection.execute(
                """
                UPDATE organization_redemption_claims
                   SET state = ?, updated_at = ?, lease_until = ?
                 WHERE attempt_id = ?
                """,
                (state, utc_iso(now), utc_iso(now), attempt_id),
            )

    def _sync_terminal_attempts_in_transaction(self) -> None:
        _ = self._connection.execute(
            """
            UPDATE organization_redemption_claims
               SET state = (SELECT status FROM redemption_attempts
                             WHERE attempt_id = organization_redemption_claims.attempt_id),
                   updated_at = (SELECT updated_at FROM redemption_attempts
                                 WHERE attempt_id = organization_redemption_claims.attempt_id)
             WHERE state IN ('claimed', 'uncertain', 'verification_failed')
               AND (SELECT status FROM redemption_attempts
                     WHERE attempt_id = organization_redemption_claims.attempt_id)
                   NOT IN ('started', 'uncertain', 'verification_failed')
            """,
        )

    def _resume_active(
        self,
        row: sqlite3.Row,
        request: ClaimRequest,
    ) -> CoordinatedAttempt:
        identity_matches = self._identity_matches(row, request)
        lease_until = parse_timestamp(
            row_text(row, "lease_until"),
            field_name="claim.lease_until",
        )
        owned = row_text(row, "lease_owner") == request.run_id
        executable = identity_matches and (owned or request.now >= lease_until)
        if executable:
            renewed_until = request.now + CLAIM_LEASE
            _ = self._connection.execute(
                """
                UPDATE organization_redemption_claims
                   SET lease_owner = ?, lease_until = ?, updated_at = ?
                 WHERE claim_id = ?
                """,
                (
                    request.run_id,
                    utc_iso(renewed_until),
                    utc_iso(request.now),
                    row_text(row, "claim_id"),
                ),
            )
            _ = self._connection.execute(
                "UPDATE redemption_attempts SET run_id = ?, updated_at = ? WHERE attempt_id = ?",
                (request.run_id, utc_iso(request.now), row_text(row, "attempt_id")),
            )
        status = (
            row_text(row, "attempt_status")
            if identity_matches
            else "active_selection_mismatch"
        )
        return CoordinatedAttempt(
            attempt_id=row_text(row, "attempt_id"),
            idempotency_key=row_text(row, "idempotency_key"),
            resumed=True,
            executable=executable,
            status=status,
        )

    @staticmethod
    def _identity_matches(row: sqlite3.Row, request: ClaimRequest) -> bool:
        selection = request.selection
        expires_at = selection.credit.expires_at
        if expires_at is None:
            return False
        return all(
            (
                row_text(row, "account_ref")
                == selection.observation.descriptor.account_ref,
                row_text(row, "credit_ref") == selection.credit.credit_ref,
                row_text(row, "expires_at") == utc_iso(expires_at),
                row_text(row, "weekly_reset_at") == utc_iso(selection.weekly_reset_at),
            ),
        )

    @staticmethod
    def _terminal_suppresses(row: sqlite3.Row, now: datetime) -> bool:
        status = row_text(row, "attempt_status")
        if status in PERMANENT_STATES:
            return True
        updated_at = parse_timestamp(
            row_text(row, "updated_at"),
            field_name="claim.updated_at",
        )
        return now - updated_at < REATTEMPT_COOLDOWN

    @staticmethod
    def _suppressed_attempt(row: sqlite3.Row) -> CoordinatedAttempt:
        return CoordinatedAttempt(
            attempt_id=row_text(row, "attempt_id"),
            idempotency_key=row_text(row, "idempotency_key"),
            resumed=True,
            executable=False,
            status=row_text(row, "attempt_status"),
        )
