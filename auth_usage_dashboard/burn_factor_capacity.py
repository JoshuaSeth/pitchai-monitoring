# Copyright (c) 2026 PitchAI. All rights reserved.
"""Horizon capacity for the burn factor: points left now plus resets, minus expiring leftovers.

The pool is simulated at a constant burn rate. Demand is served from the account
whose points expire first (window reset or subscription end), so expiring points
are used before they are lost. At a reset an account starts a fresh full window;
whatever it still had left is replaced, not added, and is reported as expiring.
When a subscription ends, its leftover is lost and it gets no further resets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, timedelta

FULL_WINDOW_POINTS = 100.0
RUNWAY_LIMIT_HOURS = 14 * 24
_EPSILON = 1e-9
_SECONDS_PER_HOUR = 3600.0


@dataclass
class AccountWindow:
    """One eligible account on the capacity basis: points left and its next reset."""

    left: float
    next_reset: datetime | None
    window: timedelta | None
    ends_at: datetime | None = None


@dataclass
class _Pool:
    accounts: list[AccountWindow]
    start: datetime
    reset_count: int = 0
    expiring: float = 0.0
    subscription_expiring: float = 0.0
    subscription_ends: int = 0
    shortfall_at: float | None = None

    def hours_until(self, moment: datetime) -> float:
        """Return the hours from the simulation start to ``moment``."""
        return (moment - self.start).total_seconds() / _SECONDS_PER_HOUR


@dataclass(frozen=True)
class Losses:
    """Leftover points lost inside the horizon: at window resets and at subscription ends."""

    at_resets: float
    at_subscription_ends: float
    subscription_end_count: int


@dataclass(frozen=True)
class HorizonCapacity:
    """Capacity available within a horizon at a given burn rate."""

    left_now_points: float
    reset_points: float
    reset_count: int
    losses: Losses
    effective_points: float
    runway_hours: float | None


def _expiry_key(account: AccountWindow) -> float:
    earliest = math.inf
    for moment in (account.next_reset, account.ends_at):
        if moment is not None:
            earliest = min(earliest, moment.timestamp())
    return earliest


def _next_event(pool: _Pool, clock: float, boundary: float) -> float:
    earliest = boundary
    for account in pool.accounts:
        for moment in (account.ends_at, account.next_reset if account.window is not None else None):
            hours = pool.hours_until(moment) if moment is not None else math.inf
            if clock + _EPSILON < hours < earliest:
                earliest = hours
    return earliest


def _serve(pool: _Pool, *, clock: float, span: float, rate: float) -> None:
    """Serve ``rate x span`` points, earliest reset first, and note the first shortfall."""
    remaining = rate * span
    for account in sorted(pool.accounts, key=_expiry_key):
        used = min(account.left, remaining)
        account.left -= used
        remaining -= used
    if remaining > _EPSILON and pool.shortfall_at is None:
        pool.shortfall_at = clock + span - remaining / rate


def _end_subscriptions(pool: _Pool, clock: float, *, inside_horizon: bool) -> None:
    for account in pool.accounts:
        if account.ends_at is not None and pool.hours_until(account.ends_at) <= clock + _EPSILON:
            if inside_horizon:
                pool.subscription_expiring += account.left
                pool.subscription_ends += 1
            account.left = 0.0
            account.next_reset = None
            account.ends_at = None


def _apply_resets(pool: _Pool, clock: float, *, inside_horizon: bool) -> None:
    _end_subscriptions(pool, clock, inside_horizon=inside_horizon)
    for account in pool.accounts:
        if account.next_reset is None or account.window is None:
            continue
        while account.next_reset is not None and pool.hours_until(account.next_reset) <= clock + _EPSILON:
            if inside_horizon:
                pool.expiring += account.left
                pool.reset_count += 1
            account.left = FULL_WINDOW_POINTS
            account.next_reset += account.window
            if account.ends_at is not None and account.next_reset >= account.ends_at:
                account.next_reset = None


def simulate(accounts: list[AccountWindow], *, start: datetime, rate: float, horizon_hours: float) -> HorizonCapacity:
    """Simulate the pool at ``rate`` points per hour over the horizon and, for runway, up to 14 days.

    Returns:
        Points left now, reset points, expiring leftovers, effective capacity and runway hours.
    """
    copies = [AccountWindow(item.left, item.next_reset, item.window, item.ends_at) for item in accounts]
    pool = _Pool(copies, start)
    left_now = sum(account.left for account in copies)
    _apply_resets(pool, 0.0, inside_horizon=True)
    limit = max(horizon_hours, float(RUNWAY_LIMIT_HOURS))
    clock = 0.0
    while clock < limit - _EPSILON and not (pool.shortfall_at is not None and clock >= horizon_hours):
        boundary = horizon_hours if clock < horizon_hours - _EPSILON else limit
        event = _next_event(pool, clock, boundary)
        if rate > 0:
            _serve(pool, clock=clock, span=event - clock, rate=rate)
        clock = event
        _apply_resets(pool, clock, inside_horizon=clock <= horizon_hours + _EPSILON)
    reset_points = FULL_WINDOW_POINTS * pool.reset_count
    return HorizonCapacity(
        left_now_points=left_now,
        reset_points=reset_points,
        reset_count=pool.reset_count,
        losses=Losses(pool.expiring, pool.subscription_expiring, pool.subscription_ends),
        effective_points=max(0.0, left_now + reset_points - pool.expiring - pool.subscription_expiring),
        runway_hours=pool.shortfall_at,
    )
