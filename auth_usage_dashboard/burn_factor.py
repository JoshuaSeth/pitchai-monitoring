# Copyright (c) 2026 PitchAI. All rights reserved.
"""Burn factor: moving capacity burn over a rolling window versus capacity over a future horizon.

``factor = burn rate x horizon / effective horizon capacity``. Below 1 the pool has
margin over the horizon at the current burn; at or above 1 it runs short.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .burn_factor_capacity import AccountWindow, simulate
from .burn_factor_results import Counts, pair_result
from .burn_factor_subscriptions import subscription_ends
from .history import parse_datetime
from .scheduling_capacity_burn_deltas import eligible_account
from .scheduling_capacity_burn_samples import measure_burn_samples
from .scheduling_capacity_burn_windows import capacity_burn_window
from .timeseries_types import nonnegative_integer, number_value, optional_object, text_value

if TYPE_CHECKING:
    from .burn_factor_windows import WindowPair
    from .timeseries_types import JsonObject, JsonValue

BASIS_KEYS = frozenset({"weekly", "five_hour"})
_HIGH_COVERAGE, _MEDIUM_COVERAGE, _SECONDS_PER_HOUR = 80.0, 20.0, 3600.0


@dataclass
class _Pool:
    windows: list[AccountWindow]
    unknown: int = 0
    ended: int = 0


def _pool(accounts: list[JsonObject], basis: str, ends: dict[str, datetime], now: datetime) -> _Pool:
    pool = _Pool([])
    for account in accounts:
        window = optional_object(account.get(basis))
        left = number_value(window.get("remaining_percent"))
        identity = (text_value(account.get("email")) or text_value(account.get("label")) or "").lower()
        ends_at = ends.get(identity)
        if ends_at is not None and ends_at <= now:
            pool.ended += 1
            continue
        if left is None:
            pool.unknown += 1
            continue
        seconds = nonnegative_integer(window.get("window_seconds"))
        reset_at = parse_datetime(text_value(window.get("reset_at")))
        length = timedelta(seconds=seconds) if seconds else None
        blocked = parse_datetime(text_value(account.get("blocked_until")))
        blocked_until = blocked if blocked is not None and blocked > now else None
        pool.windows.append(AccountWindow(max(0.0, min(100.0, left)), reset_at, length, ends_at, blocked_until))
    return pool


def _burn(
    inputs: _Inputs,
    samples: list[JsonObject],
    pair: WindowPair,
    *,
    now: datetime,
    basis: str,
) -> JsonObject:
    accounts = inputs.accounts
    # A pool whose readings refresh coarsely (Claude: about hourly) measures over at least its minimum window.
    measured_seconds = max(pair.rolling_seconds, inputs.minimum_burn_seconds)
    starts_at = now - timedelta(seconds=measured_seconds)
    totals = measure_burn_samples(accounts, samples, starts_at=starts_at, ends_at=now, window_key=basis)
    if totals.covered_seconds > 0:
        coverage = min(100.0, totals.covered_seconds / measured_seconds * 100.0)
        covered = len(totals.capacity_labels)
        confidence = (
            "high"
            if coverage >= _HIGH_COVERAGE and covered > 1
            else "medium"
            if coverage >= _MEDIUM_COVERAGE
            else "low"
        )
        rate = totals.capacity_points / (totals.covered_seconds / _SECONDS_PER_HOUR)
        return {
            "points_per_hour": rate,
            "measured_points": totals.capacity_points,
            "coverage_percent": round(coverage, 1),
            "confidence": confidence,
            "source": "native_broker_samples",
            "measured_over_seconds": measured_seconds,
        }
    estimate = capacity_burn_window(accounts, samples=[], now=now, window_hours=1, window_key=basis)
    rate = number_value(estimate.get("capacity_points_per_hour")) or 0.0
    return {
        "points_per_hour": rate,
        "measured_points": None,
        "coverage_percent": 0.0,
        "confidence": "low",
        "source": "current_window_estimate",
    }


@dataclass(frozen=True)
class _Inputs:
    """The parsed snapshot pieces every pair needs."""

    accounts: list[JsonObject]
    eligible: list[JsonObject]
    basis: str | None
    label: str | None
    minimum_burn_seconds: int


def _inputs(snapshot: JsonObject) -> _Inputs:
    summary = optional_object(snapshot.get("summary"))
    basis_object = optional_object(summary.get("capacity_basis"))
    raw_accounts = snapshot.get("accounts")
    accounts = [optional_object(item) for item in raw_accounts] if isinstance(raw_accounts, list) else []
    eligible = [account for account in accounts if eligible_account(account)]
    minimum = int(number_value(summary.get("minimum_burn_window_seconds")) or 0)
    basis_key, basis_label = text_value(basis_object.get("key")), text_value(basis_object.get("label"))
    return _Inputs(accounts, eligible, basis_key, basis_label, minimum)


def _unknown_results(pairs: list[WindowPair], reason: str) -> list[JsonValue]:
    template: JsonObject = {"factor": None, "status": "unknown", "reason": reason}
    return [{**template, "rolling": pair.rolling, "horizon": pair.horizon} for pair in pairs]


def _counts(inputs: _Inputs, pool: _Pool) -> Counts:
    saturated = sum(1 for window in pool.windows if window.left <= 0 and window.blocked_until is None)
    credited = 0
    for account in inputs.eligible:
        if optional_object(account.get("usage_credits")).get("usable") is True:
            credited += 1
    unblock_moments = (window.blocked_until for window in pool.windows)
    blocks = list(filter(None, unblock_moments))
    earliest = min(blocks).isoformat().replace("+00:00", "Z") if blocks else None
    return Counts(len(inputs.eligible), pool.unknown, saturated, credited, pool.ended, len(blocks), earliest)


def _pair_results(
    inputs: _Inputs,
    basis: str,
    samples: list[JsonObject],
    pairs: list[WindowPair],
    context: tuple[_Pool, datetime],
) -> list[JsonValue]:
    pool, moment = context
    counts = _counts(inputs, pool)
    output: list[JsonValue] = []
    for pair in pairs:
        burn = _burn(inputs, samples, pair, now=moment, basis=basis)
        rate = number_value(burn.get("points_per_hour")) or 0.0
        horizon_hours = pair.horizon_seconds / _SECONDS_PER_HOUR
        capacity = simulate(pool.windows, start=moment, rate=rate, horizon_hours=horizon_hours)
        output.append(pair_result(pair, burn, capacity, counts))
    return output


def build_burn_factors(
    snapshot: JsonObject,
    samples: list[JsonObject],
    pairs: list[WindowPair],
    *,
    subscriptions: JsonObject | None = None,
    now: datetime | None = None,
) -> JsonObject:
    """Return the burn factor for every requested pair from one capacity snapshot.

    Returns:
        Schema-1 payload with the capacity basis and one result per pair.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    inputs = _inputs(snapshot)
    payload: JsonObject = {
        "schema_version": 1,
        "generated_at": moment.isoformat().replace("+00:00", "Z"),
        "basis": {"key": inputs.basis, "label": inputs.label},
    }
    if inputs.basis is None or inputs.basis not in BASIS_KEYS:
        return {**payload, "results": _unknown_results(pairs, "No capacity basis is reported yet.")}
    if not inputs.eligible:
        return {**payload, "results": _unknown_results(pairs, "No eligible broker account.")}
    pool = _pool(inputs.eligible, inputs.basis, subscription_ends(subscriptions or {}), moment)
    return {**payload, "results": _pair_results(inputs, inputs.basis, samples, pairs, (pool, moment))}
