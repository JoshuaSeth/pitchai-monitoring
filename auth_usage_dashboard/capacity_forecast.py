# Copyright (c) 2026 PitchAI. All rights reserved.
"""Maximum near-term capacity from remaining windows plus automatic resets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from .capacity_values import parse_timestamp
from .timeseries_types import nonnegative_integer, optional_object

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject, JsonValue

FORECAST_HORIZONS = (
    ("hour", "Next hour", 60 * 60),
    ("six_hours", "Next 6 hours", 6 * 60 * 60),
    ("day", "Next 24 hours", 24 * 60 * 60),
)
_DEFAULT_WINDOW_SECONDS = 18_000
_FULL_WINDOW_POINTS = 100.0
_WINDOW_LABELS = {"five_hour": "Five-hour", "weekly": "Weekly"}


@dataclass(frozen=True)
class _Horizon:
    """One forecast horizon measured in the declared capacity-basis window."""

    now: datetime
    end: datetime
    seconds: int
    window_key: str | None


@dataclass
class _Tally:
    """Running capacity totals across the accounts of one forecast."""

    capacity_points: float = 0.0
    maximum_points: float = 0.0
    reset_events: int = 0
    weekly_blocked: int = 0
    unknown_windows: int = 0
    measured_windows: int = 0
    contributors: set[str] = field(default_factory=set[str])


def build_forecasts(accounts: list[JsonObject], *, now: datetime, window_key: str | None) -> list[JsonValue]:
    """Forecast the maximum usable capacity over each standard horizon.

    Returns:
        One capacity forecast per entry in ``FORECAST_HORIZONS``.
    """
    forecasts: list[JsonValue] = []
    for key, label, seconds in FORECAST_HORIZONS:
        horizon = _Horizon(now=now, end=now + timedelta(seconds=seconds), seconds=seconds, window_key=window_key)
        forecasts.append(_forecast(accounts, horizon, key=key, label=label))
    return forecasts


def _forecast(accounts: list[JsonObject], horizon: _Horizon, *, key: str, label: str) -> JsonObject:
    tally = _Tally()
    for account in accounts:
        if account["enabled"]:
            _tally_account(tally, account, horizon)
    if tally.measured_windows == 0:
        capacity: JsonObject = {
            "capacity_points": None,
            "account_equivalents": None,
            "maximum_points": None,
            "capacity_percent": None,
        }
        measurement_status = "unavailable"
    else:
        capacity_percent = min(100.0, tally.capacity_points / tally.maximum_points * 100.0)
        capacity = {
            "capacity_points": round(tally.capacity_points, 1),
            "account_equivalents": round(tally.capacity_points / _FULL_WINDOW_POINTS, 2),
            "maximum_points": round(tally.maximum_points, 1),
            "capacity_percent": round(capacity_percent, 1),
        }
        measurement_status = "partial" if tally.unknown_windows else "complete"
    any_enabled_stale = any(account["stale"] for account in accounts if account["enabled"])
    if not tally.measured_windows:
        confidence = "unavailable"
    elif tally.unknown_windows or any_enabled_stale:
        confidence = "partial"
    else:
        confidence = "high"
    return {
        "key": key,
        "label": label,
        "horizon_seconds": horizon.seconds,
        "basis_key": horizon.window_key,
        "basis_label": _WINDOW_LABELS.get(horizon.window_key or ""),
        **capacity,
        "measurement_status": measurement_status,
        "measured_window_accounts": tally.measured_windows,
        "unknown_window_accounts": tally.unknown_windows,
        "usable_accounts_now": sum(1 for account in accounts if account["selectable_now"] and not account["stale"]),
        "contributing_accounts": len(tally.contributors),
        "automatic_resets": tally.reset_events,
        "five_hour_resets": tally.reset_events if horizon.window_key == "five_hour" else 0,
        "weekly_blocked_accounts": tally.weekly_blocked,
        "confidence": confidence,
    }


def _tally_account(tally: _Tally, account: JsonObject, horizon: _Horizon) -> None:
    window_key = horizon.window_key
    if window_key not in {"five_hour", "weekly"}:
        tally.unknown_windows += 1
        return
    primary = optional_object(account[window_key])
    weekly_limited = account["status"] == "weekly_limited"
    if primary.get("reported") is not True:
        tally.unknown_windows += 1
        if weekly_limited:
            tally.weekly_blocked += 1
        return
    tally.measured_windows += 1
    primary_reset = parse_timestamp(primary.get("reset_at"))
    window_seconds = nonnegative_integer(primary.get("window_seconds")) or _DEFAULT_WINDOW_SECONDS
    scheduled_resets = _scheduled_resets(primary_reset, window_seconds=window_seconds, horizon=horizon)
    if primary_reset is None:
        tally.unknown_windows += 1
        theoretical_reset_count = horizon.seconds // window_seconds
    else:
        theoretical_reset_count = len(scheduled_resets)
    tally.maximum_points += _FULL_WINDOW_POINTS * (1 + theoretical_reset_count)
    weekly_reset = parse_timestamp(optional_object(account["weekly"]).get("reset_at"))
    if weekly_limited and (weekly_reset is None or weekly_reset > horizon.end):
        tally.weekly_blocked += 1
    label = str(account["label"])
    remaining = primary.get("remaining_percent")
    if account["selectable_now"] and not account["stale"] and isinstance(remaining, (int, float)) and remaining > 0:
        tally.capacity_points += float(remaining)
        tally.contributors.add(label)
    if account["auth_valid"] is not True or account["stale"]:
        return
    for reset_at in scheduled_resets:
        if window_key == "five_hour" and weekly_limited and (weekly_reset is None or reset_at < weekly_reset):
            continue
        tally.capacity_points += _FULL_WINDOW_POINTS
        tally.reset_events += 1
        tally.contributors.add(label)


def _scheduled_resets(first_reset: datetime | None, *, window_seconds: int, horizon: _Horizon) -> list[datetime]:
    if first_reset is None or window_seconds <= 0:
        return []
    step = timedelta(seconds=window_seconds)
    candidate = first_reset
    while candidate <= horizon.now:
        candidate += step
    resets: list[datetime] = []
    while candidate <= horizon.end:
        resets.append(candidate)
        candidate += step
    return resets
