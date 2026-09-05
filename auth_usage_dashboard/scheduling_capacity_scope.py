# Copyright (c) 2026 PitchAI. All rights reserved.
"""Broker-burnable scope with informational protected-account classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .scheduling_capacity_scope_values import burnable_scope_values
from .timeseries_types import number_value, optional_object, text_value

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

_WINDOW_KEYS = ("five_hour", "weekly")


@dataclass(frozen=True)
class SchedulingCapacityScope:
    """Capacity inputs the broker can burn, independent of routing order."""

    summary: JsonObject
    source: JsonObject
    runout: JsonObject
    burnable_accounts: tuple[JsonObject, ...]
    protected_capacity: JsonObject


def scheduling_capacity_scope(
    dashboard_snapshot: JsonObject,
    *,
    raw_accounts: list[JsonObject] | None = None,
    usage_samples: list[JsonObject] | None = None,
) -> SchedulingCapacityScope:
    """Build one broker-burnable scheduling scope.

    Account routing tiers are classified only to explain the broker's burn-last
    contract. An omitted ``last_resort`` marker follows the broker's standard-
    tier default. Incomplete or malformed inventory never removes otherwise
    valid capacity from admission math; concrete account ordering belongs to
    the authentication broker.

    Returns:
        Burnable inputs plus a separate identity-free routing aggregate.
    """
    accounts = _account_objects(dashboard_snapshot.get("accounts"))
    protected, unclassified = (
        _classify_embedded(accounts) if raw_accounts is None else _classify_inventory(accounts, raw_accounts)
    )
    summary, source, runout = burnable_scope_values(
        dashboard_snapshot,
        accounts,
        usage_samples=usage_samples or [],
    )
    basis_key = _basis_key(summary)
    return SchedulingCapacityScope(
        summary=summary,
        source=source,
        runout=runout,
        burnable_accounts=accounts,
        protected_capacity=_protected_capacity(
            protected,
            basis_key=basis_key,
            total_accounts=len(accounts),
            unclassified_accounts=unclassified,
        ),
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


def _classify_embedded(
    accounts: tuple[JsonObject, ...],
) -> tuple[tuple[JsonObject, ...], int]:
    protected: list[JsonObject] = []
    unclassified = 0
    for account in accounts:
        marker = account.get("last_resort")
        if marker is True:
            protected.append(account)
        elif "last_resort" in account and marker is not False:
            unclassified += 1
    return tuple(protected), unclassified


def _classify_inventory(
    accounts: tuple[JsonObject, ...],
    raw_accounts: list[JsonObject],
) -> tuple[tuple[JsonObject, ...], int]:
    tiers: dict[str, bool | None] = {}
    ambiguous: set[str] = set()
    for raw_account in raw_accounts:
        metadata = optional_object(raw_account.get("metadata"))
        label = text_value(metadata.get("label"))
        if label is None:
            continue
        if label in tiers:
            ambiguous.add(label)
            continue
        if "last_resort" not in metadata:
            tiers[label] = False
        else:
            marker = metadata.get("last_resort")
            tiers[label] = marker if isinstance(marker, bool) else None
    protected: list[JsonObject] = []
    unclassified = 0
    for account in accounts:
        label = text_value(account.get("label"))
        if label is None or label not in tiers or label in ambiguous or tiers[label] is None:
            unclassified += 1
        elif tiers[label] is True:
            protected.append(account)
    return tuple(protected), unclassified


def _protected_capacity(
    accounts: tuple[JsonObject, ...],
    *,
    basis_key: str | None,
    total_accounts: int,
    unclassified_accounts: int,
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
        "included_in_admission": True,
        "routing_owner": "authentication_broker",
        "burn_order": "last_resort",
        "classification_status": _classification_status(
            total_accounts=total_accounts,
            unclassified_accounts=unclassified_accounts,
        ),
        "unclassified_account_count": unclassified_accounts,
    }


def _classification_status(*, total_accounts: int, unclassified_accounts: int) -> str:
    if unclassified_accounts == 0:
        return "complete"
    if unclassified_accounts < total_accounts:
        return "partial"
    return "unavailable"


def _basis_key(summary: JsonObject) -> str | None:
    raw_key = optional_object(summary.get("capacity_basis")).get("key")
    return raw_key if isinstance(raw_key, str) and raw_key in _WINDOW_KEYS else None
