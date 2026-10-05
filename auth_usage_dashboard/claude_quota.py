# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parser, fail-closed guard, and row merge for the Claude ``/usage`` readout.

The pinned official binary prints plan limits through its local ``/usage``
command. This stdlib-only module (the host runs it with Python 3.10) turns the
printed limit lines into window readings, recognizes results that are not
provably local, validates stored readings, and merges them into account rows.
"""

from __future__ import annotations

import calendar
import math
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

QUOTA_SOURCE, QUOTA_WINDOWS = "claude_cli_usage", frozenset({"five_hour", "seven_day", "seven_day_sonnet"})
QUOTA_ERRORS = frozenset({
    "probe_failed",
    "probe_timeout",
    "no_limits_reported",
    "probe_guard_tripped",
    "probe_disabled",
    "binary_unavailable",
})
QUOTA_FRESH_SECONDS, ROLLOVER_SECONDS, EPOCH_MAXIMUM_SECONDS = 900.0, 15_552_000.0, 253_402_300_799.0
FULL_PERCENT, MAX_SCOPED, MAX_LABEL, HALF_DAY_HOURS, HOUR_MINUTES = 100.0, 6, 40, 12, 60
FIRST_YEAR, LAST_YEAR = 1970, 9999
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
LIMIT_LINE = re.compile(
    r"(Current session|Current week \(([^()]{1,40})\)):\s+(\d{1,3})% used(?:\s+\xb7\s+resets\s+(.+))?",
)
RESET_TEXT = re.compile(r"([A-Z][a-z]{2}) (\d{1,2}),(?: (\d{4}),)? (\d{1,2})(?::(\d{2}))?([ap]m)(?: \(UTC\))?")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
NAMED_WEEKS = {"all models": "seven_day", "Sonnet only": "seven_day_sonnet"}


def number_value(value: JsonValue) -> float | None:
    """Return one finite JSON number, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def object_value(value: JsonValue) -> JsonObject:
    """Return one JSON object, or an empty object for any other value."""
    return value if isinstance(value, dict) else {}


def label_value(value: JsonValue) -> str | None:
    """Return one short printable limit label, or nothing."""
    if not isinstance(value, str) or not 0 < len(value) <= MAX_LABEL or not value.isprintable():
        return None
    return value


def window_value(raw: JsonValue) -> JsonObject | None:
    """Return one validated ``{used_percent, resets_at}`` reading, or nothing."""
    window = object_value(raw)
    used = number_value(window.get("used_percent"))
    if used is None or not 0.0 <= used <= FULL_PERCENT:
        return None
    reset = number_value(window.get("resets_at"))
    valid_reset = reset if reset is not None and 0 < reset < EPOCH_MAXIMUM_SECONDS else None
    return {"used_percent": used, "resets_at": valid_reset}


def windows_value(raw: JsonValue) -> JsonObject:
    """Return the validated named windows of one stored reading."""
    windows: JsonObject = {}
    for key, value in object_value(raw).items():
        reading = window_value(value)
        if key in QUOTA_WINDOWS and reading is not None:
            windows[key] = reading
    return windows


def scoped_values(raw: JsonValue) -> list[JsonValue]:
    """Return the validated, labelled model-scoped weekly windows of one stored reading."""
    scoped: list[JsonValue] = []
    for item in raw[:MAX_SCOPED] if isinstance(raw, list) else []:
        reading, label = window_value(item), label_value(object_value(item).get("label"))
        if reading is not None and label is not None:
            scoped.append({"label": label, **reading})
    return scoped


def _epoch(year: int, month: int, day: int, minutes: int) -> float | None:
    if not FIRST_YEAR <= year <= LAST_YEAR or not 1 <= day <= calendar.monthrange(year, month)[1]:
        return None
    return float(calendar.timegm((year, month, day, minutes // HOUR_MINUTES, minutes % HOUR_MINUTES, 0)))


def reset_epoch(text: str, now: float) -> float | None:
    """Return the epoch of one ``Oct 10, 3:59am (UTC)`` reset; a year-less date resolves to the nearest one."""
    match = RESET_TEXT.fullmatch(text.strip())
    if match is None or match.group(1) not in MONTHS:
        return None
    hour, minute, day = int(match.group(4)), int(match.group(5) or 0), int(match.group(2))
    if not 1 <= hour <= HALF_DAY_HOURS or minute >= HOUR_MINUTES:
        return None
    afternoon = HALF_DAY_HOURS if match.group(6) == "pm" else 0
    minutes, month = (hour % HALF_DAY_HOURS + afternoon) * HOUR_MINUTES + minute, MONTHS.index(match.group(1)) + 1
    explicit = match.group(3)
    year = int(explicit) if explicit else time.gmtime(now).tm_year
    moment = _epoch(year, month, day, minutes)
    if explicit is None and (moment is None or moment < now - ROLLOVER_SECONDS):
        moment = _epoch(year + 1, month, day, minutes)
    return moment


def parse_limits(text: str, now: float) -> tuple[JsonObject, list[JsonValue]]:
    """Return the named windows and model-scoped weekly windows printed by ``/usage``."""
    windows: JsonObject = {}
    scoped: list[JsonValue] = []
    for line in text.splitlines():
        match = LIMIT_LINE.fullmatch(line.strip())
        if match is None:
            continue
        reading: JsonObject = {
            "used_percent": min(float(match.group(3)), FULL_PERCENT),
            "resets_at": reset_epoch(match.group(4) or "", now),
        }
        scope = match.group(2)
        key = "five_hour" if scope is None else NAMED_WEEKS.get(scope)
        label = label_value((scope or "").removesuffix(" only"))
        if key is not None:
            windows.setdefault(key, reading)
        elif label is not None and len(scoped) < MAX_SCOPED:
            scoped.append({"label": label, **reading})
    return windows, scoped


def _integer_zero(value: JsonValue) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def guard_reason(document: JsonValue) -> str | None:
    """Return why one readout is not a provably local zero-turn, zero-token usage result."""
    result = object_value(document)
    if result.get("type") != "result" or result.get("local_command") != "usage":
        return "not_a_local_usage_result"
    if not _integer_zero(result.get("num_turns")):
        return "model_turns_reported"
    usage = object_value(result.get("usage"))
    counts = [usage.get(key) for key in TOKEN_KEYS] + [usage[key] for key in usage if key.endswith("_tokens")]
    if not all(_integer_zero(count) for count in counts):
        return "tokens_reported"
    return None if _integer_zero(result.get("total_cost_usd", 0)) else "cost_reported"


def carried_quota(raw: JsonValue) -> JsonObject:
    """Return the validated quota fields of one previous snapshot row."""
    row = object_value(raw)
    error = row.get("quota_error")
    return {
        "windows": windows_value(row.get("windows")),
        "scoped_windows": scoped_values(row.get("scoped_windows")),
        "quota_observed_at": number_value(row.get("quota_observed_at")),
        "quota_attempted_at": number_value(row.get("quota_attempted_at")),
        "quota_error": error if isinstance(error, str) and error in QUOTA_ERRORS else None,
        "quota_source": QUOTA_SOURCE,
    }


def _limit_reset(windows: JsonObject, now: float) -> float | None:
    resets: list[float] = []
    for key in ("five_hour", "seven_day"):
        window = object_value(windows.get(key))
        used, reset = number_value(window.get("used_percent")), number_value(window.get("resets_at"))
        if used is not None and used >= FULL_PERCENT and reset is not None and reset > now:
            resets.append(reset)
    return max(resets, default=None)


def apply_quota(row: JsonObject, quota: JsonObject, *, now: float) -> JsonObject:
    """Return one account row merged with a reading: tightest fresh window, and cooldown at a full limit."""
    merged: JsonObject = {**row, **quota}
    windows = object_value(quota.get("windows"))
    observed = number_value(quota.get("quota_observed_at"))
    candidates: list[tuple[float, str]] = []
    for key in ("five_hour", "seven_day"):
        used = number_value(object_value(windows.get(key)).get("used_percent"))
        if used is not None:
            candidates.append((used, key))
    if candidates and observed is not None and 0 <= now - observed <= QUOTA_FRESH_SECONDS:
        used, key = max(candidates)  # A tie keys on the weekly window, which recovers later.
        merged.update({"window": key, "used_percent": round(used, 1), "usage_observed_at": observed})
    reset, existing = _limit_reset(windows, now), number_value(row.get("cooldown_until"))
    if row.get("status") == "ready" and reset is not None:
        merged.update({"status": "cooldown", "cooldown_until": max(reset, existing or reset)})
    return merged
