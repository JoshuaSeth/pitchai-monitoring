# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected route and reader for the redacted Claude owner snapshot."""

from __future__ import annotations

import os
import time
from asyncio import to_thread
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .claude_accounts import (
    CLAUDE_ACCOUNTS_FILE,
    PLANS,
    SCHEMA_VERSION,
    WINDOWS,
    email_value,
    load_json_object,
    member_value,
)
from .claude_quota import (
    EPOCH_MAXIMUM_SECONDS,
    FULL_PERCENT,
    QUOTA_ERRORS,
    QUOTA_FRESH_SECONDS,
    number_value,
    object_value,
    scoped_values,
    windows_value,
)
from .scheduling_web_runtime import json_response_factory

if TYPE_CHECKING:
    from collections.abc import Callable

    from .scheduling_web_runtime import Application, Response
    from .settings import DashboardSettings
    from .timeseries_types import JsonObject, JsonValue

CLAUDE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE = "AUTH_USAGE_CLAUDE_ACCOUNTS_FILE"
STATUSES = frozenset({"ready", "cooldown", "sign_in_required", "unavailable"})
ROLES = frozenset({"Primary", "Fallback"})
UNAVAILABLE_ERROR = "Claude account status is unavailable"
PARTIAL_ERROR = "Some Claude account status could not be read"
MAX_ACCOUNTS, MINIMUM_PERCENT, MAXIMUM_PERCENT = 128, 0.0, 100.0
SNAPSHOT_FRESHNESS_SECONDS, USAGE_FRESHNESS_SECONDS = 180.0, 600.0


def _iso_timestamp(value: JsonValue) -> str | None:
    number = number_value(value)
    if number is None or not 0 < number < EPOCH_MAXIMUM_SECONDS:
        return None
    return datetime.fromtimestamp(number, UTC).isoformat()


def _public_window(reading: JsonValue) -> JsonValue:
    window = object_value(reading)
    used = number_value(window.get("used_percent")) or 0.0
    public: JsonObject = {
        "used_percent": used,
        "remaining_percent": min(FULL_PERCENT, max(0.0, FULL_PERCENT - used)),
        "resets_at": _iso_timestamp(window.get("resets_at")),
    }
    return {"label": window["label"], **public} if "label" in window else public


def _quota_fields(row: JsonObject, *, now: float) -> JsonObject:
    observed_at = number_value(row.get("quota_observed_at"))
    windows = windows_value(row.get("windows"))
    public_windows: JsonObject = {}
    for key, reading in windows.items():
        public_windows[key] = _public_window(reading)
    stored_scoped = scoped_values(row.get("scoped_windows"))
    scoped: list[JsonValue] = [_public_window(reading) for reading in stored_scoped]
    return {
        "windows": public_windows,
        "scoped_windows": scoped,
        "quota_observed_at": _iso_timestamp(observed_at),
        "quota_stale": observed_at is None or not 0 <= now - observed_at <= QUOTA_FRESH_SECONDS,
        "quota_error": member_value(row.get("quota_error"), QUOTA_ERRORS),
    }


def _public_row(raw: JsonValue, *, stale: bool, now: float) -> JsonObject:
    row = object_value(raw)
    owner_at = number_value(row.get("owner_observed_at"))
    owner_fresh = owner_at is not None and 0 <= now - owner_at <= SNAPSHOT_FRESHNESS_SECONDS
    status = member_value(row.get("status"), STATUSES)
    if stale or not owner_fresh:
        status = "unavailable"
    used = number_value(row.get("used_percent"))
    observed_at = number_value(row.get("usage_observed_at"))
    return {
        "email": email_value(row.get("email")),
        "plan": member_value(row.get("plan"), PLANS),
        "role": member_value(row.get("role"), ROLES) or "Account",
        "signed_in": row.get("signed_in") is True,
        "status": status or "unavailable",
        "rotation_enabled": row.get("rotation_enabled") is True,
        "used_percent": used if used is not None and MINIMUM_PERCENT <= used <= MAXIMUM_PERCENT else None,
        "window": member_value(row.get("window"), WINDOWS),
        "usage_observed_at": _iso_timestamp(observed_at),
        "usage_stale": observed_at is None or not 0 <= now - observed_at <= USAGE_FRESHNESS_SECONDS,
        "cooldown_until": _iso_timestamp(row.get("cooldown_until")),
        **_quota_fields(row, now=now),
    }


def _unavailable_snapshot() -> JsonObject:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": None,
        "stale": True,
        "accounts": [],
        "error": UNAVAILABLE_ERROR,
    }


def read_snapshot(path: Path, *, now: float | None = None) -> JsonObject:
    """Return the dashboard-facing Claude snapshot as an explicit schema.

    Returns:
        A JSON-ready object; an unreadable or invalid snapshot yields an error
        state instead of invented accounts or usage.
    """
    current = time.time() if now is None else now
    document = load_json_object(path)
    if document is None:
        return _unavailable_snapshot()
    generated = number_value(document.get("generated_at"))
    rows = document.get("accounts")
    if document.get("schema_version") != SCHEMA_VERSION or generated is None or not isinstance(rows, list):
        return _unavailable_snapshot()
    stale = not 0 <= current - generated <= SNAPSHOT_FRESHNESS_SECONDS
    public_rows: list[JsonValue] = [_public_row(row, stale=stale, now=current) for row in rows[:MAX_ACCOUNTS]]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_timestamp(generated),
        "stale": stale,
        "accounts": public_rows,
        "error": PARTIAL_ERROR if document.get("errors") else None,
    }


def register_claude_route(
    application: Application,
    *,
    settings: DashboardSettings,
    identity_default: str | None,
    require_operator: Callable[[DashboardSettings, str | None], None],
) -> None:
    """Register the protected Claude-owner snapshot route."""

    async def claude_accounts(proxy_identity: str | None = identity_default) -> Response:
        require_operator(settings, proxy_identity)
        configured = os.environ.get(CLAUDE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE)
        snapshot_path = Path(configured) if configured else CLAUDE_ACCOUNTS_FILE
        payload = await to_thread(read_snapshot, snapshot_path)
        return json_response_factory(payload)

    application.add_api_route(
        "/api/v1/claude-accounts",
        claude_accounts,
        methods=["GET"],
        response_model=None,
    )
