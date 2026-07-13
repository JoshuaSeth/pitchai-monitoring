from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import NormalDist
from typing import Any

from .history import capacity_burn_rate, parse_datetime


UTC = timezone.utc
HORIZONS = (
    ("hour", "Next hour", 60 * 60),
    ("six_hours", "Next 6 hours", 6 * 60 * 60),
    ("day", "Next 24 hours", 24 * 60 * 60),
)
SCENARIO_COUNT = 199


def build_runout_forecast(
    accounts: list[dict[str, Any]],
    *,
    samples: list[dict[str, Any]],
    reset_bank: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    now = now.astimezone(UTC)
    measured_accounts = [
        account
        for account in accounts
        if account.get("enabled")
        and account.get("auth_valid") is True
        and not account.get("stale")
        and account.get("five_hour", {}).get("reported") is True
        and isinstance(account.get("five_hour", {}).get("remaining_percent"), (int, float))
    ]
    if not measured_accounts:
        return _unavailable_forecast(accounts, reset_bank=reset_bank, now=now)

    burn = capacity_burn_rate(accounts, samples=samples, now=now)
    base_rate = float(burn["capacity_points_per_hour"])
    variation = float(burn["coefficient_of_variation"])
    rates = _scenario_rates(base_rate, variation=variation)
    initial, events = _capacity_schedule(accounts, now=now, horizon_seconds=24 * 60 * 60)
    initial_points = sum(initial.values())
    usable_now = sum(1 for value in initial.values() if value > 0)
    weekly_blocked = sum(1 for account in accounts if account.get("status") == "weekly_limited")
    near_weekly = sum(
        1
        for account in accounts
        if account.get("status") == "available"
        and isinstance(account.get("weekly", {}).get("remaining_percent"), (int, float))
        and account["weekly"]["remaining_percent"] <= 15
    )
    banked_count = int(reset_bank.get("total_available") or 0)

    horizons: list[dict[str, Any]] = []
    for key, label, seconds in HORIZONS:
        end = now + timedelta(seconds=seconds)
        relevant_events = [event for event in events if event["at"] <= end]
        runout_times = [
            runout
            for rate in rates
            if (runout := _first_runout(
                initial,
                relevant_events,
                now=now,
                horizon_end=end,
                burn_rate_per_hour=rate,
            ))
            is not None
        ]
        probability = round(len(runout_times) / len(rates) * 100.0) if rates else 0
        risk = _risk(probability)
        runout_times.sort()
        expected = _percentile_time(runout_times, 0.5)
        window_start = _percentile_time(runout_times, 0.25)
        window_end = _percentile_time(runout_times, 0.75)
        resets = sum(1 for event in relevant_events if event["capacity_points"] > 0)
        reset_points = sum(float(event["capacity_points"]) for event in relevant_events)
        horizons.append(
            {
                "key": key,
                "label": label,
                "horizon_seconds": seconds,
                "probability_percent": probability,
                "risk": risk,
                "expected_runout_at": _isoformat(expected),
                "likely_window_start": _isoformat(window_start),
                "likely_window_end": _isoformat(window_end),
                "initial_capacity_points": round(initial_points, 1),
                "scheduled_five_hour_resets": resets,
                "scheduled_capacity_points": round(reset_points, 1),
                "scenario_count": len(rates),
            }
        )

    highest = max(horizons, key=lambda item: item["probability_percent"], default=None)
    drivers = [
        f"{base_rate:.1f} capacity points/hour at the current burn estimate",
        f"{usable_now} selectable account{'s' if usable_now != 1 else ''} with {initial_points:.0f} points now",
    ]
    if weekly_blocked:
        drivers.append(f"{weekly_blocked} account{'s are' if weekly_blocked != 1 else ' is'} weekly blocked")
    if near_weekly:
        drivers.append(f"{near_weekly} usable account{'s have' if near_weekly != 1 else ' has'} 15% or less weekly headroom")
    if banked_count:
        drivers.append(f"{banked_count} banked reset{'s are' if banked_count != 1 else ' is'} excluded until manually redeemed")
    return {
        "data_available": True,
        "generated_at": _isoformat(now),
        "burn_rate": burn,
        "initial_capacity_points": round(initial_points, 1),
        "usable_accounts_now": usable_now,
        "horizons": horizons,
        "highest_risk": highest["risk"] if highest else "low",
        "highest_probability_percent": highest["probability_percent"] if highest else 0,
        "drivers": drivers,
        "banked_reset_policy": {
            "available_count": banked_count,
            "included_as_automatic_capacity": False,
            "reason": "Banked resets require an explicit redemption action; this dashboard is read-only.",
        },
        "methodology": {
            "model": "deterministic lognormal burn scenarios with earliest-expiry capacity scheduling",
            "scenario_count": len(rates),
            "automatic_resets_included": ["five_hour", "weekly_eligibility"],
            "weekly_handling": "Weekly exhaustion blocks an account until reset; weekly percentages are not converted into five-hour capacity points.",
            "limitations": "The model assumes the broker consumes capacity that expires soonest and that the estimated burn distribution remains stable.",
        },
    }


def _unavailable_forecast(
    accounts: list[dict[str, Any]],
    *,
    reset_bank: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    usable_now = sum(
        1
        for account in accounts
        if account.get("enabled") and account.get("selectable_now") and not account.get("stale")
    )
    weekly_blocked = sum(1 for account in accounts if account.get("status") == "weekly_limited")
    banked_count = int(reset_bank.get("total_available") or 0)
    horizons = [
        {
            "key": key,
            "label": label,
            "horizon_seconds": seconds,
            "probability_percent": None,
            "risk": "unknown",
            "expected_runout_at": None,
            "likely_window_start": None,
            "likely_window_end": None,
            "initial_capacity_points": None,
            "scheduled_five_hour_resets": 0,
            "scheduled_capacity_points": None,
            "scenario_count": 0,
        }
        for key, label, seconds in HORIZONS
    ]
    drivers = [
        "Provider five-hour capacity windows are not currently reported",
        f"{usable_now} account{'s are' if usable_now != 1 else ' is'} selectable from broker state",
    ]
    if weekly_blocked:
        drivers.append(f"{weekly_blocked} account{'s are' if weekly_blocked != 1 else ' is'} weekly blocked")
    if banked_count:
        drivers.append(f"{banked_count} banked reset{'s are' if banked_count != 1 else ' is'} excluded until manually redeemed")
    return {
        "data_available": False,
        "generated_at": _isoformat(now),
        "burn_rate": {
            "capacity_points_per_hour": None,
            "coefficient_of_variation": None,
            "lookback_hours": 2,
            "source": "unavailable",
            "covered_accounts": 0,
            "confidence": "unavailable",
        },
        "initial_capacity_points": None,
        "usable_accounts_now": usable_now,
        "horizons": horizons,
        "highest_risk": "unknown",
        "highest_probability_percent": None,
        "drivers": drivers,
        "banked_reset_policy": {
            "available_count": banked_count,
            "included_as_automatic_capacity": False,
            "reason": "Banked resets require an explicit redemption action; this dashboard is read-only.",
        },
        "methodology": {
            "model": "unavailable until at least one provider five-hour window is reported",
            "scenario_count": 0,
            "automatic_resets_included": [],
            "weekly_handling": "Weekly percentages remain visible but cannot substitute for missing five-hour capacity data.",
            "limitations": "Unknown five-hour capacity is not interpreted as either full or exhausted.",
        },
    }


def _capacity_schedule(
    accounts: list[dict[str, Any]],
    *,
    now: datetime,
    horizon_seconds: int,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    horizon_end = now + timedelta(seconds=horizon_seconds)
    initial: dict[str, float] = {}
    events: list[dict[str, Any]] = []
    for account in accounts:
        if not account.get("enabled") or account.get("auth_valid") is not True or account.get("stale"):
            continue
        if account.get("five_hour", {}).get("reported") is not True:
            continue
        label = str(account["label"])
        remaining = account.get("five_hour", {}).get("remaining_percent")
        initial[label] = (
            float(remaining)
            if account.get("selectable_now") and isinstance(remaining, (int, float)) and remaining > 0
            else 0.0
        )
        primary = account.get("five_hour", {})
        first_reset = parse_datetime(primary.get("reset_at"))
        window_seconds = int(primary.get("window_seconds") or 18_000)
        weekly_limited = account.get("status") == "weekly_limited"
        weekly_reset = parse_datetime(account.get("weekly", {}).get("reset_at"))
        candidate = first_reset
        if candidate is None or window_seconds <= 0:
            continue
        while candidate <= now:
            candidate += timedelta(seconds=window_seconds)
        while candidate <= horizon_end:
            eligible = not weekly_limited or (weekly_reset is not None and candidate >= weekly_reset)
            events.append(
                {
                    "at": candidate,
                    "account_label": label,
                    "capacity_points": 100.0 if eligible else 0.0,
                }
            )
            candidate += timedelta(seconds=window_seconds)
    events.sort(key=lambda event: (event["at"], event["account_label"]))
    return initial, events


def _scenario_rates(mean: float, *, variation: float) -> list[float]:
    if mean <= 0:
        return [0.0]
    cv = min(1.5, max(0.15, variation))
    sigma_squared = math.log(1.0 + cv * cv)
    sigma = math.sqrt(sigma_squared)
    mu = math.log(mean) - sigma_squared / 2.0
    normal = NormalDist()
    return [
        math.exp(mu + sigma * normal.inv_cdf((index + 0.5) / SCENARIO_COUNT))
        for index in range(SCENARIO_COUNT)
    ]


def _first_runout(
    initial: dict[str, float],
    events: list[dict[str, Any]],
    *,
    now: datetime,
    horizon_end: datetime,
    burn_rate_per_hour: float,
) -> datetime | None:
    capacities = dict(initial)
    expiries = _next_expiries(capacities, events, horizon_end=horizon_end)
    cursor = now
    if sum(capacities.values()) <= 0:
        return now
    for event in [*events, {"at": horizon_end, "account_label": None, "capacity_points": None}]:
        event_at = min(event["at"], horizon_end)
        hours = max(0.0, (event_at - cursor).total_seconds() / 3600.0)
        demand = burn_rate_per_hour * hours
        available = sum(capacities.values())
        if demand > available + 1e-9:
            if burn_rate_per_hour <= 0:
                return None
            return cursor + timedelta(hours=available / burn_rate_per_hour)
        _consume(capacities, expiries, demand)
        cursor = event_at
        label = event.get("account_label")
        if label is not None:
            capacities[label] = float(event["capacity_points"])
            expiries[label] = _following_expiry(label, events, after=event_at, horizon_end=horizon_end)
        if cursor >= horizon_end:
            break
    return None


def _consume(
    capacities: dict[str, float],
    expiries: dict[str, datetime],
    demand: float,
) -> None:
    for label in sorted(capacities, key=lambda item: (expiries.get(item, datetime.max.replace(tzinfo=UTC)), item)):
        if demand <= 0:
            return
        consumed = min(capacities[label], demand)
        capacities[label] -= consumed
        demand -= consumed


def _next_expiries(
    capacities: dict[str, float],
    events: list[dict[str, Any]],
    *,
    horizon_end: datetime,
) -> dict[str, datetime]:
    return {
        label: _following_expiry(label, events, after=None, horizon_end=horizon_end)
        for label in capacities
    }


def _following_expiry(
    label: str,
    events: list[dict[str, Any]],
    *,
    after: datetime | None,
    horizon_end: datetime,
) -> datetime:
    for event in events:
        if event["account_label"] == label and (after is None or event["at"] > after):
            return event["at"]
    return horizon_end + timedelta(seconds=1)


def _percentile_time(values: list[datetime], percentile: float) -> datetime | None:
    if not values:
        return None
    index = round((len(values) - 1) * percentile)
    return values[max(0, min(len(values) - 1, index))]


def _risk(probability: int) -> str:
    if probability >= 60:
        return "high"
    if probability >= 25:
        return "medium"
    return "low"


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
