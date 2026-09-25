# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deliver requester-private guardian alerts and classify safe errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .clients import AccountScanError, RemoteCallError
from .command_notifier import NotificationError
from .guardian_types import Alert
from .models import PayloadError

if TYPE_CHECKING:
    from .guardian_types import GuardianDependencies, GuardianRunSummary


def safe_error_code(exc: Exception) -> str:
    """Return a sanitized and stable error code for known boundaries."""
    if isinstance(exc, RemoteCallError):
        return f"{exc.endpoint}:{exc.error_code}"
    if isinstance(exc, AccountScanError):
        return exc.error_code
    if isinstance(exc, PayloadError):
        return f"payload:{type(exc).__name__}"
    if isinstance(exc, NotificationError):
        return f"notification:{exc.error_code}"
    return f"unexpected:{type(exc).__name__}"


def send_alerts(
    dependencies: GuardianDependencies,
    *,
    run_id: str,
    summary: GuardianRunSummary,
    alerts: list[Alert],
) -> None:
    """Send every due alert and persist each batch outcome.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    notifier = dependencies.notifier
    if notifier is None:
        msg = "alert delivery requires a configured notifier"
        raise RuntimeError(msg)
    due: list[Alert] = [
        alert
        for alert in alerts
        if dependencies.audit.notification_due(
            notification_key=alert.key,
            run_id=run_id,
            now=dependencies.clock(),
        )
    ]
    for batch in alert_batches(due):
        lines = ["<b>Codex reset guardian</b>"]
        lines.extend(alert.line for alert in batch)
        message = "\n".join(lines)
        try:
            notifier(message)
        except NotificationError as exc:
            _record_failed_batch(dependencies, run_id, summary, batch, exc)
            continue
        _record_sent_batch(dependencies, run_id, batch)


def _record_failed_batch(
    dependencies: GuardianDependencies,
    run_id: str,
    summary: GuardianRunSummary,
    batch: list[Alert],
    error: NotificationError,
) -> None:
    keys = [alert.key for alert in batch]
    dependencies.audit.record_notification_result(
        notification_keys=keys,
        now=dependencies.clock(),
        sent=False,
        error_code=error.error_code,
    )
    dependencies.audit.record_event(
        run_id=run_id,
        now=dependencies.clock(),
        event_type="notification_failed",
        severity="error",
        details={"error_code": error.error_code, "alert_count": len(batch)},
    )
    summary.error_count += 1
    summary.notification_error_count += 1


def _record_sent_batch(
    dependencies: GuardianDependencies,
    run_id: str,
    batch: list[Alert],
) -> None:
    keys = [alert.key for alert in batch]
    dependencies.audit.record_notification_result(
        notification_keys=keys,
        now=dependencies.clock(),
        sent=True,
        error_code=None,
    )
    dependencies.audit.record_event(
        run_id=run_id,
        now=dependencies.clock(),
        event_type="notification_sent",
        details={"alert_count": len(batch), "route": "requester_private"},
    )


def alert_batches(
    alerts: list[Alert],
    *,
    maximum_length: int = 3800,
) -> list[list[Alert]]:
    """Split alert lines into bounded Telegram-safe message batches.

    Returns:
        The resulting collection.

    """
    header_length = len("<b>Codex reset guardian</b>\n")
    batches: list[list[Alert]] = []
    current: list[Alert] = []
    current_length = header_length
    for alert in alerts:
        current_alert = alert
        line_length = len(current_alert.line) + 1
        if current and current_length + line_length > maximum_length:
            batches.append(current)
            current = []
            current_length = header_length
        if line_length + header_length > maximum_length:
            bounded_line = current_alert.line[: maximum_length - header_length - 2] + "…"
            current_alert = Alert(key=current_alert.key, line=bounded_line)
            line_length = len(current_alert.line) + 1
        current.append(current_alert)
        current_length += line_length
    if current:
        batches.append(current)
    return batches
