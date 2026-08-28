# Copyright (c) 2026 PitchAI. All rights reserved.
"""Identity-free expiry timeline for scheduling-capacity consumers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING

from .scheduling_capacity_timeline_values import aware_datetime
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    optional_object,
    text_value,
)

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject, JsonValue

_TIMELINE_HORIZON = timedelta(days=8)


@dataclass(frozen=True)
class SchedulingCapacityTimeline:
    """One bounded redacted capacity timeline for the selected provider window."""

    status: str
    current_points: float | None
    expiry_buckets: list[JsonValue]
    automatic_resets: list[JsonValue]


@dataclass(slots=True)
class _ExpiryAggregate:
    count: int = 0
    remaining_points: float = 0.0


@dataclass(slots=True)
class _ResetAggregate:
    count: int = 0
    capacity_points: float = 0.0
    restores_selectability_count: int = 0


@dataclass(frozen=True)
class _TimelineContext:
    basis_key: str
    observed_at: datetime


@dataclass(frozen=True)
class _TimelineGroups:
    expiry: defaultdict[datetime, _ExpiryAggregate]
    resets: defaultdict[tuple[datetime, datetime], _ResetAggregate]
    complete: bool
    current_points: float


def scheduling_capacity_timeline(
    raw_accounts: JsonValue,
    *,
    basis_key: str | None,
    generated_at: str | None,
) -> SchedulingCapacityTimeline:
    """Build the current expiry buckets and bounded automatic reset arrivals.

    Returns:
        Aggregate-only timeline. Missing expiry evidence is explicit and never
        converted into available capacity.
    """
    observed_at = aware_datetime(generated_at)
    if basis_key not in {"five_hour", "weekly"} or observed_at is None or not isinstance(raw_accounts, list):
        return SchedulingCapacityTimeline("unavailable", None, [], [])
    measured = _measured_accounts(raw_accounts, basis_key=basis_key)
    if not measured:
        return SchedulingCapacityTimeline("unavailable", None, [], [])
    groups = _aggregate_accounts(
        measured,
        context=_TimelineContext(basis_key, observed_at),
    )
    if not groups.expiry:
        return SchedulingCapacityTimeline("unavailable", None, [], [])
    expiry_buckets = _expiry_rows(groups.expiry, basis_key=basis_key, observed_at=observed_at)
    automatic_resets = _reset_rows(groups.resets, basis_key=basis_key, observed_at=observed_at)
    status = "complete" if groups.complete else "partial"
    return SchedulingCapacityTimeline(
        status,
        round(groups.current_points, 1),
        expiry_buckets,
        automatic_resets,
    )


def _aggregate_accounts(
    accounts: list[JsonObject],
    *,
    context: _TimelineContext,
) -> _TimelineGroups:
    expiry_groups: defaultdict[datetime, _ExpiryAggregate] = defaultdict(_ExpiryAggregate)
    reset_groups: defaultdict[tuple[datetime, datetime], _ResetAggregate] = defaultdict(_ResetAggregate)
    complete = True
    current_points = 0.0
    for account in accounts:
        window = optional_object(account.get(context.basis_key))
        reset_at = aware_datetime(text_value(window.get("reset_at")))
        window_seconds = nonnegative_integer(window.get("window_seconds"))
        if reset_at is None or window_seconds is None or window_seconds < 1:
            complete = False
            continue
        remaining = number_value(window.get("remaining_percent")) or 0.0
        usable_remaining = remaining if account.get("selectable_now") is True else 0.0
        current_points += usable_remaining
        expiry = expiry_groups[reset_at]
        expiry.count += 1
        expiry.remaining_points += usable_remaining
        _add_account_resets(
            reset_groups,
            account=account,
            first_reset=reset_at,
            window_seconds=window_seconds,
            context=context,
        )
    return _TimelineGroups(expiry_groups, reset_groups, complete, current_points)


def _expiry_rows(
    groups: defaultdict[datetime, _ExpiryAggregate],
    *,
    basis_key: str,
    observed_at: datetime,
) -> list[JsonValue]:
    rows: list[JsonValue] = []
    for at, aggregate in sorted(groups.items()):
        at_text = at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        in_seconds = max(0, int((at - observed_at).total_seconds()))
        rows.append(
            {
                "kind": f"{basis_key}_window",
                "at": at_text,
                "in_seconds": in_seconds,
                "count": aggregate.count,
                "remaining_points": round(aggregate.remaining_points, 1),
            },
        )
    return rows


def _reset_rows(
    groups: defaultdict[tuple[datetime, datetime], _ResetAggregate],
    *,
    basis_key: str,
    observed_at: datetime,
) -> list[JsonValue]:
    rows: list[JsonValue] = []
    for (at, expires_at), aggregate in sorted(groups.items()):
        if aggregate.capacity_points <= 0.0:
            continue
        at_text = at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        expires_at_text = expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        in_seconds = max(0, int((at - observed_at).total_seconds()))
        rows.append(
            {
                "kind": f"{basis_key}_reset",
                "at": at_text,
                "in_seconds": in_seconds,
                "expires_at": expires_at_text,
                "count": aggregate.count,
                "capacity_points": round(aggregate.capacity_points, 1),
                "restores_selectability_count": aggregate.restores_selectability_count,
            },
        )
    return rows


def _measured_accounts(raw_accounts: list[JsonValue], *, basis_key: str) -> list[JsonObject]:
    accounts: list[JsonObject] = []
    for value in raw_accounts:
        account = optional_object(value)
        window = optional_object(account.get(basis_key))
        remaining = number_value(window.get("remaining_percent"))
        measured = (
            account.get("enabled") is True
            and account.get("auth_valid") is True
            and account.get("stale") is not True
            and window.get("reported") is True
            and remaining is not None
        )
        if measured:
            accounts.append(account)
    return accounts


def _add_account_resets(
    groups: defaultdict[tuple[datetime, datetime], _ResetAggregate],
    *,
    account: JsonObject,
    first_reset: datetime,
    window_seconds: int,
    context: _TimelineContext,
) -> None:
    horizon = context.observed_at + _TIMELINE_HORIZON
    reset_at = first_reset
    while reset_at <= context.observed_at:
        reset_at += timedelta(seconds=window_seconds)
    first = True
    while reset_at <= horizon:
        expires_at = reset_at + timedelta(seconds=window_seconds)
        capacity_points = _reset_capacity_points(
            account,
            basis_key=context.basis_key,
            reset_at=reset_at,
        )
        aggregate = groups[reset_at, expires_at]
        aggregate.count += 1
        aggregate.capacity_points += capacity_points
        restores_selectability = account.get("status") == f"{context.basis_key}_limited"
        if first and restores_selectability:
            aggregate.restores_selectability_count += 1
        reset_at = expires_at
        first = False


def _reset_capacity_points(account: JsonObject, *, basis_key: str, reset_at: datetime) -> float:
    if basis_key == "weekly" or account.get("status") != "weekly_limited":
        return 100.0
    weekly = optional_object(account.get("weekly"))
    weekly_reset = aware_datetime(text_value(weekly.get("reset_at")))
    return 100.0 if weekly_reset is not None and reset_at >= weekly_reset else 0.0
