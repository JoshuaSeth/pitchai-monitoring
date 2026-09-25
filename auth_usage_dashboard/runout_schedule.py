# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build and consume deterministic provider reset schedules."""

from __future__ import annotations

from datetime import timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, NamedTuple

from .runout_basis import capacity_window
from .runout_consumption import consume, following_expiry, next_expiries
from .value_parsing import parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityAccount, CapacityScheduleEvent


class AccountSchedule(NamedTuple):
    """Represent one account's initial capacity and reset events."""

    label: str
    initial: float
    events: list[CapacityScheduleEvent]


class EventScheduleInputs(NamedTuple):
    """Bundle one account's recurring reset schedule parameters."""

    label: str
    reset_at: datetime
    horizon_end: datetime
    window_seconds: int
    window_key: str


def capacity_schedule(
    accounts: list[CapacityAccount],
    *,
    now: datetime,
    horizon_seconds: int,
    window_key: str,
) -> tuple[dict[str, float], list[CapacityScheduleEvent]]:
    """Build initial capacity and automatic resets within one horizon.

    Returns:
        The resulting collection.

    """
    horizon_end = now + timedelta(seconds=horizon_seconds)
    initial: dict[str, float] = {}
    events: list[CapacityScheduleEvent] = []
    for account in accounts:
        schedule = _account_schedule(
            account,
            now=now,
            horizon_end=horizon_end,
            window_key=window_key,
        )
        if schedule is not None:
            initial[schedule.label] = schedule.initial
            events.extend(schedule.events)
    events.sort(key=itemgetter("at", "account_label"))
    return initial, events


def _account_schedule(
    account: CapacityAccount,
    *,
    now: datetime,
    horizon_end: datetime,
    window_key: str,
) -> AccountSchedule | None:
    if not _eligible_account(account):
        return None
    primary = capacity_window(account, window_key)
    if not primary["reported"]:
        return None
    label = str(account["label"])
    initial = _initial_capacity(account, remaining=primary["remaining_percent"])
    reset_at = parse_datetime(primary["reset_at"])
    window_seconds = primary["window_seconds"] or 18_000
    if reset_at is None or window_seconds <= 0:
        return AccountSchedule(label, initial, [])
    reset_at = _next_reset(reset_at, now=now, window_seconds=window_seconds)
    events = _account_events(
        account,
        EventScheduleInputs(
            label,
            reset_at,
            horizon_end,
            window_seconds,
            window_key,
        ),
    )
    return AccountSchedule(label, initial, events)


def _eligible_account(account: CapacityAccount) -> bool:
    return bool(
        account.get("enabled") and account.get("auth_valid") is True and not account.get("stale"),
    )


def _initial_capacity(
    account: CapacityAccount,
    *,
    remaining: float | None,
) -> float:
    if account.get("selectable_now") and remaining is not None and remaining > 0:
        return float(remaining)
    return 0.0


def _next_reset(
    reset_at: datetime,
    *,
    now: datetime,
    window_seconds: int,
) -> datetime:
    while reset_at <= now:
        reset_at += timedelta(seconds=window_seconds)
    return reset_at


def _account_events(
    account: CapacityAccount,
    inputs: EventScheduleInputs,
) -> list[CapacityScheduleEvent]:
    events: list[CapacityScheduleEvent] = []
    weekly_limited = account.get("status") == "weekly_limited"
    weekly_reset = parse_datetime(account["weekly"]["reset_at"])
    reset_at = inputs.reset_at
    while reset_at <= inputs.horizon_end:
        eligible = (
            inputs.window_key == "weekly"
            or not weekly_limited
            or (weekly_reset is not None and reset_at >= weekly_reset)
        )
        events.append(
            {
                "at": reset_at,
                "account_label": inputs.label,
                "capacity_points": 100.0 if eligible else 0.0,
            },
        )
        reset_at += timedelta(seconds=inputs.window_seconds)
    return events


def first_runout(
    initial: dict[str, float],
    events: list[CapacityScheduleEvent],
    *,
    now: datetime,
    horizon_end: datetime,
    burn_rate_per_hour: float,
) -> datetime | None:
    """Return the first capacity exhaustion time within one schedule."""
    capacities = dict(initial)
    expiries = next_expiries(capacities, events, horizon_end=horizon_end)
    cursor = now
    if sum(capacities.values()) <= 0:
        return now
    for event in events:
        event_at = min(event["at"], horizon_end)
        runout = _consume_until(
            capacities,
            expiries,
            cursor=cursor,
            end=event_at,
            burn_rate_per_hour=burn_rate_per_hour,
        )
        if runout is not None:
            return runout
        cursor = event_at
        _apply_event(capacities, expiries, event, events, horizon_end=horizon_end)
        if cursor >= horizon_end:
            break
    if cursor < horizon_end:
        return _consume_until(
            capacities,
            expiries,
            cursor=cursor,
            end=horizon_end,
            burn_rate_per_hour=burn_rate_per_hour,
        )
    return None


def _consume_until(
    capacities: dict[str, float],
    expiries: dict[str, datetime],
    *,
    cursor: datetime,
    end: datetime,
    burn_rate_per_hour: float,
) -> datetime | None:
    hours = max(0.0, (end - cursor).total_seconds() / 3600.0)
    demand = burn_rate_per_hour * hours
    available = sum(capacities.values())
    if demand > available + 1e-9:
        if burn_rate_per_hour <= 0:
            return None
        return cursor + timedelta(hours=available / burn_rate_per_hour)
    consume(capacities, expiries, demand)
    return None


def _apply_event(
    capacities: dict[str, float],
    expiries: dict[str, datetime],
    event: CapacityScheduleEvent,
    events: list[CapacityScheduleEvent],
    *,
    horizon_end: datetime,
) -> None:
    label = event["account_label"]
    capacities[label] = event["capacity_points"]
    expiries[label] = following_expiry(
        label,
        events,
        after=event["at"],
        horizon_end=horizon_end,
    )
