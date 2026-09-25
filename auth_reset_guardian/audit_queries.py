# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build stable guardian status and recent-event query payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .audit_notifications import NotificationAuditStore
from .audit_types import (
    json_object,
    optional_int,
    optional_text,
    required_int,
    required_text,
    select_connection,
)

if TYPE_CHECKING:
    from .audit_types import (
        SqlRow,
    )
    from .json_contract import JsonObject, JsonValue


class AuditStore(NotificationAuditStore):
    """Store sanitized guardian state without provider or OAuth secrets."""

    def latest_status(self) -> JsonObject:
        """Return the latest run, accounts, and redemption attempts."""
        run = (
            select_connection(self._connection)
            .execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1",
            )
            .fetchone()
        )
        upcoming = (
            select_connection(self._connection)
            .execute(
                """
            SELECT account_label, captured_at, state_json
              FROM snapshots
             WHERE snapshot_id IN (
                 SELECT MAX(snapshot_id) FROM snapshots GROUP BY account_ref
             )
             ORDER BY account_label
            """,
            )
            .fetchall()
        )
        attempts = (
            select_connection(self._connection)
            .execute(
                """
            SELECT account_label, credit_ref, expires_at, started_at, updated_at,
                   status, outcome, windows_reset, verification, error_code
              FROM redemption_attempts ORDER BY started_at DESC LIMIT 20
            """,
            )
            .fetchall()
        )
        latest_accounts: list[JsonValue] = [
            {
                "account_label": required_text(row, "account_label"),
                "captured_at": required_text(row, "captured_at"),
                "state": json_object(row, "state_json"),
            }
            for row in upcoming
        ]
        recent_attempts: list[JsonValue] = [_attempt_record(row) for row in attempts]
        return {
            "latest_run": _run_record(run) if run else None,
            "latest_accounts": latest_accounts,
            "recent_redemption_attempts": recent_attempts,
        }

    def recent_events(self, *, limit: int) -> list[JsonObject]:
        """Return recent events in descending audit order."""
        rows = (
            select_connection(self._connection)
            .execute(
                "SELECT * FROM events ORDER BY event_id DESC LIMIT ?",
                (limit,),
            )
            .fetchall()
        )
        return [_event_record(row) for row in rows]


def _run_record(row: SqlRow) -> JsonObject:
    """Convert one run row into its stable status payload.

    Returns:
        The resulting value.

    """
    return {
        "run_id": required_text(row, "run_id"),
        "mode": required_text(row, "mode"),
        "started_at": required_text(row, "started_at"),
        "completed_at": optional_text(row, "completed_at"),
        "status": required_text(row, "status"),
        "account_count": required_int(row, "account_count"),
        "credit_count": required_int(row, "credit_count"),
        "warning_count": required_int(row, "warning_count"),
        "redemption_count": required_int(row, "redemption_count"),
        "error_count": required_int(row, "error_count"),
        "summary_json": optional_text(row, "summary_json"),
    }


def _attempt_record(row: SqlRow) -> JsonObject:
    """Convert one redemption-attempt row into a status payload.

    Returns:
        The resulting value.

    """
    return {
        "account_label": required_text(row, "account_label"),
        "credit_ref": required_text(row, "credit_ref"),
        "expires_at": required_text(row, "expires_at"),
        "started_at": required_text(row, "started_at"),
        "updated_at": required_text(row, "updated_at"),
        "status": required_text(row, "status"),
        "outcome": optional_text(row, "outcome"),
        "windows_reset": optional_int(row, "windows_reset"),
        "verification": optional_text(row, "verification"),
        "error_code": optional_text(row, "error_code"),
    }


def _event_record(row: SqlRow) -> JsonObject:
    """Convert one event row into its stable audit API payload.

    Returns:
        The resulting value.

    """
    return {
        "event_id": required_int(row, "event_id"),
        "run_id": required_text(row, "run_id"),
        "occurred_at": required_text(row, "occurred_at"),
        "event_type": required_text(row, "event_type"),
        "severity": required_text(row, "severity"),
        "account_ref": optional_text(row, "account_ref"),
        "account_label": optional_text(row, "account_label"),
        "credit_ref": optional_text(row, "credit_ref"),
        "expires_at": optional_text(row, "expires_at"),
        "threshold_hours": optional_int(row, "threshold_hours"),
        "attempt_id": optional_text(row, "attempt_id"),
        "details_json": required_text(row, "details_json"),
    }
