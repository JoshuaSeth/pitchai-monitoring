# Copyright (c) 2026 PitchAI. All rights reserved.
"""Broker-burnable aggregate and burn values for scheduling capacity."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .runout import build_runout_forecast, select_capacity_basis
from .scheduling_capacity_timeline_values import aware_datetime
from .timeseries_types import number_value, optional_object, text_value

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

_WINDOW_KEYS = ("five_hour", "weekly")


def burnable_scope_values(
    dashboard_snapshot: JsonObject,
    accounts: tuple[JsonObject, ...],
    *,
    usage_samples: list[JsonObject],
) -> tuple[JsonObject, JsonObject, JsonObject]:
    """Calculate broker-burnable summary, freshness, and runout evidence.

    Returns:
        The three source projections consumed by the scheduler contract.
    """
    summary = _burnable_summary(accounts)
    source = _burnable_source(
        optional_object(dashboard_snapshot.get("source")),
        accounts,
    )
    runout = _burnable_runout(
        dashboard_snapshot,
        accounts,
        usage_samples=usage_samples,
        summary=summary,
    )
    return summary, source, runout


def _burnable_summary(accounts: tuple[JsonObject, ...]) -> JsonObject:
    raw_basis = select_capacity_basis(list(accounts))
    capacity_basis = cast("JsonObject", cast("object", raw_basis))
    eligible = tuple(account for account in accounts if _capacity_eligible(account))
    aggregates: JsonObject = {}
    for key in _WINDOW_KEYS:
        aggregates[key] = _window_aggregate(eligible, key=key)
    usable_now = sum(1 for account in eligible if account.get("selectable_now") is True)
    return {
        "usable_now": usable_now,
        "capacity_basis": capacity_basis,
        "window_aggregates": aggregates,
    }


def _window_aggregate(
    accounts: tuple[JsonObject, ...],
    *,
    key: str,
) -> JsonObject:
    remaining_points = 0.0
    reporting = 0
    for account in accounts:
        window = optional_object(account.get(key))
        remaining = number_value(window.get("remaining_percent"))
        if window.get("reported") is True and remaining is not None:
            reporting += 1
            remaining_points += remaining
    maximum_points = float(reporting * 100)
    return {
        "measurement_status": _measurement_status(reporting, eligible=len(accounts)),
        "reporting_accounts": reporting,
        "unknown_accounts": len(accounts) - reporting,
        "remaining_points": round(remaining_points, 1) if reporting else None,
        "maximum_known_points": maximum_points if reporting else None,
        "remaining_percent": round(remaining_points / maximum_points * 100.0, 1)
        if reporting
        else None,
    }


def _measurement_status(reporting: int, *, eligible: int) -> str:
    if reporting == 0:
        return "unavailable"
    return "complete" if reporting == eligible else "partial"


def _burnable_source(
    source: JsonObject,
    accounts: tuple[JsonObject, ...],
) -> JsonObject:
    projection = dict(source)
    projection["stale_account_count"] = sum(
        1
        for account in accounts
        if account.get("enabled") is True
        and account.get("auth_valid") is True
        and account.get("stale") is True
    )
    probe_times: list[str] = []
    for account in accounts:
        if account.get("enabled") is True and account.get("auth_valid") is True:
            probe_at = text_value(account.get("last_probe_at"))
            if probe_at is not None:
                probe_times.append(probe_at)
    if probe_times:
        projection["newest_account_probe_at"] = max(probe_times)
    return projection


def _burnable_runout(
    dashboard_snapshot: JsonObject,
    accounts: tuple[JsonObject, ...],
    *,
    usage_samples: list[JsonObject],
    summary: JsonObject,
) -> JsonObject:
    generated_at = text_value(dashboard_snapshot.get("generated_at"))
    now = aware_datetime(generated_at)
    if now is None:
        message = "operator scheduling snapshot has an invalid generated timestamp"
        raise ValueError(message)
    labels: set[str] = set()
    for account in accounts:
        label = text_value(account.get("label"))
        if _capacity_eligible(account) and label is not None:
            labels.add(label)
    filtered_samples = _samples_for_labels(usage_samples, labels=labels)
    raw_runout = build_runout_forecast(
        list(accounts),
        samples=filtered_samples,
        reset_bank=optional_object(dashboard_snapshot.get("reset_bank")),
        now=now,
        capacity_basis=optional_object(summary.get("capacity_basis")),
    )
    return cast("JsonObject", cast("object", raw_runout))


def _samples_for_labels(
    samples: list[JsonObject],
    *,
    labels: set[str],
) -> list[JsonObject]:
    filtered: list[JsonObject] = []
    for sample in samples:
        raw_accounts = sample.get("accounts")
        if not isinstance(raw_accounts, dict):
            filtered.append(sample)
            continue
        selected: JsonObject = {}
        for label, value in raw_accounts.items():
            if label in labels:
                selected[label] = value
        filtered.append({**sample, "accounts": selected})
    return filtered


def _capacity_eligible(account: JsonObject) -> bool:
    return (
        account.get("enabled") is True
        and account.get("auth_valid") is True
        and account.get("stale") is not True
    )
