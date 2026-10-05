# Copyright (c) 2026 PitchAI. All rights reserved.
"""Account pools for the burn factor beyond the Codex broker: Claude and OpenCode Go.

Each pool's redacted exporter snapshot is mapped onto the broker account shape
the burn factor already understands: a weekly basis window plus a
``blocked_until`` when another window (Claude's 5-hour, OpenCode's rolling or
monthly) is exhausted. Burn comes from each pool's own sample history.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .claude_accounts import load_json_object
from .history import isoformat, parse_datetime
from .pool_samples import read_samples
from .timeseries_types import number_value, optional_object, text_value

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

DATA_DIR = Path("/dashboard-data")
WEEK_SECONDS = 7 * 86_400
QUOTA_FRESH_SECONDS = 900.0
FULL_PERCENT = 100.0
WEEKLY_BASIS: JsonObject = {"key": "weekly", "label": "Weekly"}
POOL_LABELS: JsonObject = {
    "openai": "OpenAI · Codex account broker",
    "anthropic": "Anthropic · Claude Code accounts",
    "opencode": "OpenCode Go · MiMo/GLM subscription pool",
    "deepseek": "DeepSeek API · prepaid balance",
}


def _iso(epoch: float | None) -> str | None:
    return isoformat(datetime.fromtimestamp(epoch, UTC)) if epoch is not None else None


def _weekly(used: float, reset_at: str | None) -> JsonObject:
    remaining = max(0.0, FULL_PERCENT - used)
    return {
        "remaining_percent": remaining,
        "used_percent": used,
        "reported": True,
        "reset_at": reset_at,
        "window_seconds": WEEK_SECONDS,
    }


def _latest(moments: list[datetime | None]) -> str | None:
    present = [moment for moment in moments if moment is not None]
    return isoformat(max(present)) if present else None


def claude_accounts(snapshot: JsonObject, *, now: float) -> list[JsonValue]:
    """Return Claude profiles as burn-factor accounts (weekly basis, 5-hour window as blocker)."""
    rows = snapshot.get("accounts")
    accounts: list[JsonValue] = []
    for raw in rows if isinstance(rows, list) else []:
        row = optional_object(raw)
        windows = optional_object(row.get("windows"))
        week, five = optional_object(windows.get("seven_day")), optional_object(windows.get("five_hour"))
        used = number_value(week.get("used_percent"))
        observed = number_value(row.get("quota_observed_at"))
        five_used = number_value(five.get("used_percent"))
        five_reset = number_value(five.get("resets_at"))
        blocked = five_reset if five_used is not None and five_used >= FULL_PERCENT and five_reset is not None else None
        accounts.append({
            "label": text_value(row.get("email")) or text_value(row.get("id")) or "claude",
            "enabled": True,
            "auth_valid": row.get("signed_in") is True,
            "stale": observed is None or not 0 <= now - observed <= QUOTA_FRESH_SECONDS,
            "weekly": _weekly(used, _iso(number_value(week.get("resets_at")))) if used is not None else {},
            "blocked_until": _iso(blocked),
        })
    return accounts


def _opencode_blocks(windows: JsonObject, cooldown: float | None, now: float) -> list[datetime | None]:
    """Return the reset of every exhausted rolling/monthly window plus an active bridge cooldown."""
    blockers: list[datetime | None] = []
    for name in ("rolling", "monthly"):
        window = optional_object(windows.get(name))
        exhausted = (number_value(window.get("used_percent")) or 0.0) >= FULL_PERCENT
        if exhausted or window.get("status") == "rate-limited":
            blockers.append(parse_datetime(text_value(window.get("resets_at"))))
    blockers.append(datetime.fromtimestamp(cooldown, UTC) if cooldown is not None and cooldown > now else None)
    return blockers


def opencode_accounts(snapshot: JsonObject, *, now: float) -> list[JsonValue]:
    """Return OpenCode Go subscriptions as accounts (weekly basis; rolling, monthly and cooldowns block)."""
    generated = number_value(snapshot.get("generated_at"))
    fresh = generated is not None and 0 <= now - generated <= QUOTA_FRESH_SECONDS
    rows = snapshot.get("accounts")
    accounts: list[JsonValue] = []
    for raw in rows if isinstance(rows, list) else []:
        row = optional_object(raw)
        windows = optional_object(row.get("windows"))
        week = optional_object(windows.get("weekly"))
        used = number_value(week.get("used_percent"))
        blockers = _opencode_blocks(windows, number_value(row.get("cooldown_until")), now)
        accounts.append({
            "label": text_value(row.get("label")) or "opencode",
            "enabled": True,
            "auth_valid": row.get("auth_valid") is True,
            "stale": not fresh or row.get("error") is not None,
            "weekly": _weekly(used, text_value(week.get("resets_at"))) if used is not None else {},
            "blocked_until": _latest(blockers),
        })
    return accounts


def pool_inputs(
    pool: str,
    *,
    data_dir: Path = DATA_DIR,
    now: float | None = None,
) -> tuple[JsonObject, list[JsonObject]]:
    """Return a broker-shaped snapshot and the sample history for the Claude or OpenCode pool."""
    current = time.time() if now is None else now
    if pool == "anthropic":
        snapshot = load_json_object(data_dir / "claude-accounts.json") or {}
        accounts = claude_accounts(snapshot, now=current)
        samples = read_samples(data_dir / "claude-usage-samples.json")
    else:
        snapshot = load_json_object(data_dir / "opencode-accounts.json") or {}
        accounts = opencode_accounts(snapshot, now=current)
        samples = read_samples(data_dir / "opencode-usage-samples.json")
    summary: JsonObject = {"capacity_basis": WEEKLY_BASIS if accounts else {"key": None, "label": None}}
    return {"summary": summary, "accounts": accounts}, samples
