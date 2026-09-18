# Copyright (c) 2026 PitchAI. All rights reserved.
"""Critical-production-only Telegram delivery for database failure groups."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from httpx import Client

from .json_types import (
    float_value,
    normalize_json,
    object_list,
    text_value,
)
from .state_io import write_state

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonObject, JsonValue

_DASHBOARD_URL = "https://monitoring.pitchai.net/dashboard#databases"
_MAX_MESSAGE_CHARS = 3_800
_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX = 300


class DatabaseDependencyAlertConfigurationError(RuntimeError):
    """A pending critical alert cannot use the configured Telegram route."""


class DatabaseDependencyAlertDeliveryError(RuntimeError):
    """Telegram did not accept a persisted critical alert."""


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        message = f"{name} is required for pending database alerts"
        raise DatabaseDependencyAlertConfigurationError(message)
    return value


def _timestamp(value: JsonValue) -> str:
    timestamp = float_value(value)
    if timestamp is None:
        return "never"
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _legacy_member(alert: JsonObject) -> JsonObject:
    return {
        "affected_app": alert.get("affected_app"),
        "container": alert.get("container"),
        "failure_class": alert.get("failure_class"),
        "credential_state": alert.get("credential_state"),
        "last_success_at_ts": alert.get("last_success_at_ts"),
        "owner_project": alert.get("owner_project"),
        "likely_fix_path": alert.get("likely_fix_path"),
        "sanitized_error_excerpt": alert.get("sanitized_error_excerpt"),
    }


def _members(alert: JsonObject) -> list[JsonObject]:
    members = object_list(alert.get("members"))
    if members:
        return members
    if text_value(alert.get("dependency_id")):
        return [_legacy_member(alert)]
    message = "pending database alert has no affected members"
    raise DatabaseDependencyAlertConfigurationError(message)


def _member_lines(member: JsonObject, *, index: int) -> tuple[str, ...]:
    return (
        (
            f"{index}. {text_value(member.get('affected_app'), default='unknown app')}"
            f" · {text_value(member.get('container'), default='unknown container')}"
        ),
        f"   Failure: {text_value(member.get('failure_class'), default='unknown')}",
        f"   Credential: {text_value(member.get('credential_state'), default='unproven')}",
        f"   Last success: {_timestamp(member.get('last_success_at_ts'))}",
        f"   Owner/project: {text_value(member.get('owner_project'), default='unassigned')}",
        f"   Likely fix: {text_value(member.get('likely_fix_path'), default='inspect app DB route')}",
        f"   Evidence: {text_value(member.get('sanitized_error_excerpt'), default='no safe excerpt')}",
    )


def _message(alert: JsonObject) -> str:
    group = text_value(alert.get("alert_group"), default="production-database")
    lines = ["CRITICAL production database dependency DOWN", f"Alert group: {group}"]
    for index, member in enumerate(_members(alert), start=1):
        lines.extend(_member_lines(member, index=index))
    lines.append(_DASHBOARD_URL)
    return "\n".join(lines)[:_MAX_MESSAGE_CHARS]


def _post_alert(client: Client, *, token: str, chat_id: str, alert: JsonObject) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = client.post(url, json={"chat_id": chat_id, "text": _message(alert)})
    if not _HTTP_SUCCESS_MIN <= response.status_code < _HTTP_SUCCESS_MAX:
        message = f"Telegram rejected a database alert with HTTP {response.status_code}"
        raise DatabaseDependencyAlertDeliveryError(message)


def deliver_pending_alerts(state: JsonObject, *, state_path: Path) -> JsonObject:
    """Deliver grouped alerts and checkpoint each accepted Telegram response.

    Returns:
        The state with every delivered alert removed from its pending queue.
    """
    pending = object_list(state.get("pending_alerts"))
    if not pending:
        return state
    token = _required_environment("TELEGRAM_BOT_TOKEN")
    chat_id = _required_environment("TELEGRAM_CHAT_ID")
    client_factory = partial(Client, timeout=15.0, follow_redirects=False, trust_env=False)
    with client_factory() as client:
        while pending:
            _post_alert(client, token=token, chat_id=chat_id, alert=pending[0])
            _ = pending.pop(0)
            state["pending_alerts"] = normalize_json(pending)
            write_state(state_path, state)
    return state
