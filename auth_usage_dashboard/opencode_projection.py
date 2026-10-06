# Copyright (c) 2026 PitchAI. All rights reserved.
"""Redacted OpenCode Go subscription list for the dashboard and the native apps.

Every subscription in the isolated bridge's rotating keyring is listed with its
rolling 5-hour, weekly and monthly windows. The windows use the same shape as
the Codex broker windows, so clients reuse their window rows. Each subscription
gets a status: ``ready``, ``limited`` (a window is used up), ``cooldown`` (the
bridge holds the key back after a 429), ``auth_invalid`` or ``unavailable``.
OpenCode Go has no banked resets; the monthly window renews per subscription.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .claude_accounts import load_json_object
from .history import isoformat, parse_datetime
from .timeseries_types import number_value, optional_object, text_value

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

OPENCODE_ACCOUNTS_FILE = Path("/dashboard-data/opencode-accounts.json")
WINDOWS = ("rolling", "weekly", "monthly")
WINDOW_SECONDS: dict[str, int | None] = {"rolling": 5 * 3_600, "weekly": 7 * 86_400, "monthly": None}
SNAPSHOT_FRESH_SECONDS = 900.0
FULL_PERCENT = 100.0
UNAVAILABLE_ERROR = "OpenCode subscription status is unavailable"
_EXHAUSTED_STATUS = "rate-limited"


def _iso_epoch(epoch: float | None) -> str | None:
    return isoformat(datetime.fromtimestamp(epoch, UTC)) if epoch is not None else None


def project_window(name: str, raw: JsonValue, *, now: float) -> JsonObject:
    """Return one window in the Codex broker window shape plus OpenCode's own status text."""
    window = optional_object(raw)
    used = number_value(window.get("used_percent"))
    reset = parse_datetime(text_value(window.get("resets_at")))
    return {
        "reported": used is not None,
        "used_percent": used,
        "remaining_percent": None if used is None else max(0.0, FULL_PERCENT - used),
        "reset_at": isoformat(reset) if reset is not None else None,
        "reset_in_seconds": max(0, int(reset.timestamp() - now)) if reset is not None else None,
        "window_seconds": WINDOW_SECONDS.get(name),
        "status": text_value(window.get("status")),
    }


def _exhausted(window: JsonObject) -> bool:
    used = number_value(window.get("used_percent"))
    return (used is not None and used >= FULL_PERCENT) or window.get("status") == _EXHAUSTED_STATUS


def _status(row: JsonObject, *, limited: bool, cooling: bool) -> str:
    if row.get("auth_valid") is False:
        return "auth_invalid"
    if row.get("error") is not None:
        return "unavailable"
    if limited:
        return "limited"
    return "cooldown" if cooling else "ready"


def project_account(row: JsonObject, position: int, *, now: float) -> JsonObject:
    """Return one subscription with its windows, status and the moment it becomes usable again."""
    raw_windows = optional_object(row.get("windows"))
    windows: JsonObject = {}
    limited_by: list[JsonValue] = []
    blocked_until: list[float] = []
    for name in WINDOWS:
        window = project_window(name, raw_windows.get(name), now=now)
        windows[name] = window
        reset = parse_datetime(text_value(window.get("reset_at")))
        if _exhausted(window):
            limited_by.append(name)
            blocked_until.append(reset.timestamp() if reset is not None else now)
    cooldown = number_value(row.get("cooldown_until"))
    cooling = cooldown is not None and cooldown > now
    if cooling and cooldown is not None:
        blocked_until.append(cooldown)
    status = _status(row, limited=bool(limited_by), cooling=cooling)
    return {
        "label": text_value(row.get("label")) or f"subscription-{position}",
        "position": position,
        "status": status,
        "limited_by": limited_by,
        "available_at": _iso_epoch(max(blocked_until)) if blocked_until and status != "ready" else None,
        "windows": windows,
        "bridge_last_status": number_value(row.get("last_status")),
        "bridge_cooldown_until": _iso_epoch(cooldown) if cooling else None,
        "error": text_value(row.get("error")),
    }


def project_opencode(snapshot: JsonObject | None, *, now: float) -> JsonObject:
    """Return the subscription list with a pool summary, or an explicit unavailable state."""
    rows = snapshot.get("accounts") if snapshot is not None else None
    accounts: list[JsonValue] = []
    for position, raw in enumerate(rows if isinstance(rows, list) else [], start=1):
        accounts.append(project_account(optional_object(raw), position, now=now))
    projected = [optional_object(account) for account in accounts]
    waiting = [text_value(account.get("available_at")) for account in projected]
    upcoming = sorted(moment for moment in waiting if moment is not None)
    generated = number_value(snapshot.get("generated_at")) if snapshot is not None else None
    return {
        "schema_version": 1,
        "generated_at": _iso_epoch(generated),
        "stale": generated is None or not 0 <= now - generated <= SNAPSHOT_FRESH_SECONDS,
        "error": None if snapshot is not None else UNAVAILABLE_ERROR,
        "summary": {
            "subscriptions": len(projected),
            "ready": sum(1 for account in projected if account.get("status") == "ready"),
            "limited": sum(1 for account in projected if account.get("status") == "limited"),
            "next_available_at": upcoming[0] if upcoming else None,
        },
        "accounts": accounts,
    }


def load_opencode(path: Path, *, now: float | None = None) -> JsonObject:
    """Read the exporter snapshot at ``path`` and project it at ``now`` (the current time by default).

    Returns:
        The projected subscription list, explicitly unavailable when the snapshot cannot be read.
    """
    current = time.time() if now is None else now
    return project_opencode(load_json_object(path), now=current)
