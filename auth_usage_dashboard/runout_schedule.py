# Copyright (c) 2026 PitchAI. All rights reserved.
"""Current capacity and scheduled automatic resets for runout forecasts."""

from __future__ import annotations

from datetime import datetime, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, TypedDict

from .history_values import eligible_accounts, parse_datetime, whole_number
from .runout_basis import account_window

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

type ForecastPeriod = tuple[datetime, datetime]

_DEFAULT_WINDOW_SECONDS = 18_000
_FULL_WINDOW_POINTS = 100.0


class ResetEvent(TypedDict):
    """One automatic window reset that restores account capacity."""

    at: datetime
    account_label: str
    capacity_points: float


def capacity_schedule(
    accounts: list[JsonObject],
    *,
    now: datetime,
    horizon_seconds: int,
    window_key: str,
) -> tuple[dict[str, float], list[ResetEvent]]:
    """Return selectable capacity now and every reset inside the horizon.

    Returns:
        Initial capacity points per account label and chronologically ordered
        reset events.
    """
    period = now, now + timedelta(seconds=horizon_seconds)
    initial: dict[str, float] = {}
    events: list[ResetEvent] = []
    for account in eligible_accounts(accounts):
        if account_window(account, window_key).get("reported") is not True:
            continue
        label = str(account["label"])
        initial[label] = _initial_points(account, window_key=window_key)
        events.extend(_account_resets(account, label=label, window_key=window_key, period=period))
    events.sort(key=itemgetter("at", "account_label"))
    return initial, events


def _initial_points(account: JsonObject, *, window_key: str) -> float:
    remaining = account_window(account, window_key).get("remaining_percent")
    if account.get("selectable_now") and isinstance(remaining, (int, float)) and remaining > 0:
        return float(remaining)
    return 0.0


def _account_resets(
    account: JsonObject,
    *,
    label: str,
    window_key: str,
    period: ForecastPeriod,
) -> list[ResetEvent]:
    now, horizon_end = period
    primary = account_window(account, window_key)
    first_reset = parse_datetime(primary.get("reset_at"))
    window_seconds = whole_number(primary.get("window_seconds") or _DEFAULT_WINDOW_SECONDS)
    weekly_limited = account.get("status") == "weekly_limited"
    weekly_reset = parse_datetime(account_window(account, "weekly").get("reset_at"))
    if first_reset is None or window_seconds <= 0:
        return []
    step = timedelta(seconds=window_seconds)
    candidate = first_reset
    while candidate <= now:
        candidate += step
    resets: list[ResetEvent] = []
    while candidate <= horizon_end:
        eligible = (
            window_key == "weekly" or not weekly_limited or (weekly_reset is not None and candidate >= weekly_reset)
        )
        resets.append({
            "at": candidate,
            "account_label": label,
            "capacity_points": _FULL_WINDOW_POINTS if eligible else 0.0,
        })
        candidate += step
    return resets
