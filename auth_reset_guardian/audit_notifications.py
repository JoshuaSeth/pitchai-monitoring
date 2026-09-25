# Copyright (c) 2026 PitchAI. All rights reserved.
"""Persist guardian notification delivery state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .audit_redemptions import RedemptionAuditStore
from .audit_types import required_text, select_connection
from .models import utc_iso

if TYPE_CHECKING:
    from datetime import datetime


class NotificationAuditStore(RedemptionAuditStore):
    """Deduplicate notifications and retain delivery outcomes."""

    def notification_due(
        self,
        *,
        notification_key: str,
        run_id: str,
        now: datetime,
    ) -> bool:
        """Return whether a notification still requires successful delivery."""
        row = (
            select_connection(self._connection)
            .execute(
                "SELECT status FROM notifications WHERE notification_key = ?",
                (notification_key,),
            )
            .fetchone()
        )
        if row is not None:
            return required_text(row, "status") != "sent"
        with self._connection:
            _ = self._connection.execute(
                """
                INSERT INTO notifications(notification_key, first_run_id, first_seen_at, status)
                VALUES (?, ?, ?, 'pending')
                """,
                (notification_key, run_id, utc_iso(now)),
            )
        return True

    def record_notification_result(
        self,
        *,
        notification_keys: list[str],
        now: datetime,
        sent: bool,
        error_code: str | None,
    ) -> None:
        """Persist a batch notification attempt result."""
        rows: list[tuple[str, str, str | None, str]] = [
            (utc_iso(now), "sent" if sent else "failed", error_code, key) for key in notification_keys
        ]
        with self._connection:
            _ = self._connection.executemany(
                """
                UPDATE notifications
                   SET last_attempt_at = ?, attempts = attempts + 1,
                       status = ?, last_error_code = ?
                 WHERE notification_key = ?
                """,
                rows,
            )
