# Copyright (c) 2026 PitchAI. All rights reserved.
"""Verified standard-versus-protected account scope for priority admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .scheduling_capacity_scope_values import standard_scope_values
from .timeseries_types import number_value, optional_object, text_value

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

_WINDOW_KEYS = ("five_hour", "weekly")


@dataclass(frozen=True)
class SchedulingCapacityScope:
    """Capacity inputs proven to contain only ordinary routing-tier accounts."""

    summary: JsonObject
    source: JsonObject
    runout: JsonObject
    standard_accounts: tuple[JsonObject, ...]
    protected_capacity: JsonObject


def scheduling_capacity_scope(
    dashboard_snapshot: JsonObject,
    *,
    raw_accounts: list[JsonObject] | None = None,
    usage_samples: list[JsonObject] | None = None,
) -> SchedulingCapacityScope:
    """Build one fail-closed, standard-only scheduling scope.

    A live call supplies the raw broker inventory so the immutable routing-tier
    bit can be joined to the redacted operator accounts. Tests and captured
    snapshots may instead carry an explicit boolean ``last_resort`` marker on
    every account.

    Returns:
        Standard-only inputs plus a separate identity-free protected aggregate.
    """
    accounts = _account_objects(dashboard_snapshot.get("accounts"))
    if raw_accounts is None:
        standard, protected = _split_embedded(accounts)
        summary = optional_object(dashboard_snapshot.get("summary"))
        source = optional_object(dashboard_snapshot.get("source"))
        runout = optional_object(dashboard_snapshot.get("runout_forecast"))
    else:
        standard, protected = _split_inventory(accounts, raw_accounts)
        summary, source, runout = standard_scope_values(
            dashboard_snapshot,
            standard,
            usage_samples=usage_samples or [],
        )
    basis_key = _basis_key(summary)
    return SchedulingCapacityScope(
        summary=summary,
        source=source,
        runout=runout,
        standard_accounts=standard,
        protected_capacity=_protected_capacity(protected, basis_key=basis_key),
    )


def _account_objects(raw_accounts: JsonValue) -> tuple[JsonObject, ...]:
    if not isinstance(raw_accounts, list):
        message = "operator scheduling accounts must be an array"
        raise TypeError(message)
    accounts: list[JsonObject] = []
    for raw_account in raw_accounts:
        if not isinstance(raw_account, dict):
            message = "operator scheduling account must be an object"
            raise TypeError(message)
        accounts.append(raw_account)
    return tuple(accounts)


def _split_embedded(
    accounts: tuple[JsonObject, ...],
) -> tuple[tuple[JsonObject, ...], tuple[JsonObject, ...]]:
    standard: list[JsonObject] = []
    protected: list[JsonObject] = []
    for account in accounts:
        marker = account.get("last_resort")
        if not isinstance(marker, bool):
            message = "captured scheduling account lacks an explicit routing tier"
            raise TypeError(message)
        (protected if marker else standard).append(account)
    return tuple(standard), tuple(protected)


def _split_inventory(
    accounts: tuple[JsonObject, ...],
    raw_accounts: list[JsonObject],
) -> tuple[tuple[JsonObject, ...], tuple[JsonObject, ...]]:
    tiers: dict[str, bool] = {}
    for raw_account in raw_accounts:
        metadata = optional_object(raw_account.get("metadata"))
        label = text_value(metadata.get("label")) or "Unlabeled account"
        if label in tiers:
            message = "broker routing inventory contains a duplicate account label"
            raise ValueError(message)
        tiers[label] = metadata.get("last_resort") is True
    if len(tiers) != len(accounts):
        message = "broker routing inventory does not match the operator snapshot"
        raise ValueError(message)
    standard: list[JsonObject] = []
    protected: list[JsonObject] = []
    for account in accounts:
        label = text_value(account.get("label"))
        if label is None or label not in tiers:
            message = "broker routing inventory cannot classify an operator account"
            raise ValueError(message)
        (protected if tiers[label] else standard).append(account)
    return tuple(standard), tuple(protected)


def _protected_capacity(
    accounts: tuple[JsonObject, ...], *, basis_key: str | None,
) -> JsonObject:
    enabled = tuple(account for account in accounts if account.get("enabled") is True)
    measured: list[JsonObject] = []
    if basis_key is not None:
        for account in enabled:
            window = optional_object(account.get(basis_key))
            remaining = number_value(window.get("remaining_percent"))
            if (
                account.get("auth_valid") is True
                and account.get("stale") is not True
                and window.get("reported") is True
                and remaining is not None
            ):
                measured.append(account)
    remaining_points = 0.0
    usable_accounts = 0
    for account in measured:
        if account.get("selectable_now") is True and basis_key is not None:
            usable_accounts += 1
            remaining_points += (
                number_value(
                    optional_object(account.get(basis_key)).get("remaining_percent"),
                )
                or 0.0
            )
    return {
        "account_count": len(enabled),
        "reporting_accounts": len(measured),
        "usable_accounts_now": usable_accounts,
        "remaining_points": round(remaining_points, 1) if measured else None,
        "maximum_known_points": float(len(measured) * 100) if measured else None,
        "included_in_admission": False,
    }


def _basis_key(summary: JsonObject) -> str | None:
    raw_key = optional_object(summary.get("capacity_basis")).get("key")
    return raw_key if isinstance(raw_key, str) and raw_key in _WINDOW_KEYS else None
