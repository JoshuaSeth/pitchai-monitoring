# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validated operator projection of auth-broker Luna reserve capacity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .timeseries_types import (
    nonnegative_integer,
    number_value,
    require_object,
    text_value,
)

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

LUNA_RESERVE_SCHEMA_VERSION = 1
_BROKER_CAPACITY_SCHEMA_VERSION = 1
_RESERVE_MODEL = "gpt-reserve"
_QUALITY_TIER = "luna"
_METERED_FEATURE = "base_model_inference"
_MAXIMUM_PERCENT = 100.0
_SUPPORTED_HEALTH = frozenset(
    {
        "healthy",
        "protected_only",
        "exhausted_or_below_floor",
        "unavailable",
    },
)


def build_luna_reserve_snapshot(raw_payload: JsonValue) -> JsonObject:
    """Validate and redact the broker aggregate for the operator dashboard.

    Returns:
        Identity-free reserve totals, reset timing, health, and routing policy.

    Raises:
        ValueError: If the broker response violates the reserve contract.
    """
    payload = require_object(raw_payload, description="auth-broker capacity response")
    schema_version = nonnegative_integer(payload.get("schema_version"))
    if schema_version != _BROKER_CAPACITY_SCHEMA_VERSION:
        message = "auth-broker capacity schema version is unsupported"
        raise ValueError(message)
    observed_at = _required_text(payload, "observed_at")
    reserve = require_object(payload.get("luna_reserve"), description="Luna reserve aggregate")
    _validate_exact_meter(reserve)
    capacity = _capacity_values(reserve)
    observed_accounts = _required_nonnegative_integer(reserve, "observed_accounts")
    latest_observed_at = text_value(reserve.get("latest_observed_at"))
    health = _dashboard_health(
        _required_choice(reserve, "health", _SUPPORTED_HEALTH),
        active_routable_points=capacity["active_routable_points"],
        safe_drain_points=capacity["safe_drain_points"],
    )
    reliability = "provider_meter_observed" if observed_accounts > 0 and latest_observed_at else "unverified"
    return {
        "schema_version": LUNA_RESERVE_SCHEMA_VERSION,
        "observed_at": observed_at,
        "source": "auth_broker_identity_free_aggregate",
        "luna_reserve": {
            "model": _RESERVE_MODEL,
            "quality_tier": _QUALITY_TIER,
            "metered_feature": _METERED_FEATURE,
            "reserve_only": True,
            "safety_floor_percent": _required_percentage(reserve, "safety_floor_percent"),
            "observed_accounts": observed_accounts,
            "healthy_standard_accounts": _required_nonnegative_integer(
                reserve,
                "healthy_standard_accounts",
            ),
            "healthy_last_resort_accounts": _required_nonnegative_integer(
                reserve,
                "healthy_last_resort_accounts",
            ),
            "active_routable_accounts": _required_nonnegative_integer(
                reserve,
                "active_routable_accounts",
            ),
            **capacity,
            "active_routable_account_equivalents": round(
                capacity["active_routable_points"] / _MAXIMUM_PERCENT,
                2,
            ),
            "remaining_percent_min": _optional_percentage(reserve, "remaining_percent_min"),
            "remaining_percent_max": _optional_percentage(reserve, "remaining_percent_max"),
            "remaining_percent_average": _optional_percentage(
                reserve,
                "remaining_percent_average",
            ),
            "next_reset_at": text_value(reserve.get("next_reset_at")),
            "latest_reset_at": text_value(reserve.get("latest_reset_at")),
            "oldest_observed_at": text_value(reserve.get("oldest_observed_at")),
            "latest_observed_at": latest_observed_at,
            "health": health,
            "reliability_status": reliability,
            "cost_status": "separate_meter_exact_price_not_exposed",
            "quality_policy": "luna_equivalent_low_medium_max_no_ultra",
        },
    }


def _validate_exact_meter(reserve: JsonObject) -> None:
    _required_choice(reserve, "model", {_RESERVE_MODEL})
    _required_choice(reserve, "quality_tier", {_QUALITY_TIER})
    _required_choice(reserve, "metered_feature", {_METERED_FEATURE})
    if not _required_flag(reserve, "reserve_only"):
        message = "Luna reserve aggregate is not marked reserve-only"
        raise ValueError(message)


def _capacity_values(reserve: JsonObject) -> dict[str, float]:
    maximum_points = _required_nonnegative_number(reserve, "maximum_known_points")
    remaining_points = _required_nonnegative_number(reserve, "remaining_points")
    safe_drain_points = _required_nonnegative_number(reserve, "safe_drain_points")
    active_points = _required_nonnegative_number(reserve, "active_routable_points")
    if remaining_points > maximum_points:
        message = "Luna reserve remaining points exceed measured capacity"
        raise ValueError(message)
    if active_points > safe_drain_points:
        message = "Luna active-routable points exceed standard safe-drain capacity"
        raise ValueError(message)
    return {
        "maximum_known_points": maximum_points,
        "remaining_points": remaining_points,
        "safe_drain_points": safe_drain_points,
        "active_routable_points": active_points,
        "stranded_safe_drain_points": _required_nonnegative_number(
            reserve,
            "stranded_safe_drain_points",
        ),
        "protected_last_resort_points": _required_nonnegative_number(
            reserve,
            "protected_last_resort_points",
        ),
    }


def _dashboard_health(
    broker_health: str,
    *,
    active_routable_points: float,
    safe_drain_points: float,
) -> str:
    if broker_health == "healthy":
        return "active_routable" if active_routable_points > 0.0 else "available_but_stranded"
    if broker_health == "protected_only":
        return "protected_only"
    if broker_health == "exhausted_or_below_floor":
        return "exhausted_or_unhealthy"
    if safe_drain_points > 0.0:
        message = "unavailable Luna health cannot advertise safe-drain capacity"
        raise ValueError(message)
    return "unavailable"


def _required_text(payload: JsonObject, key: str) -> str:
    value = text_value(payload.get(key))
    if value is None:
        message = f"Luna reserve response is missing text {key}"
        raise ValueError(message)
    return value


def _required_choice(payload: JsonObject, key: str, choices: set[str] | frozenset[str]) -> str:
    value = _required_text(payload, key)
    if value not in choices:
        message = f"Luna reserve response has unsupported value {key}"
        raise ValueError(message)
    return value


def _required_flag(payload: JsonObject, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        message = f"Luna reserve response is missing boolean {key}"
        raise TypeError(message)
    return value


def _required_nonnegative_number(payload: JsonObject, key: str) -> float:
    value = number_value(payload.get(key))
    if value is None or value < 0.0:
        message = f"Luna reserve response is missing non-negative number {key}"
        raise ValueError(message)
    return value


def _required_nonnegative_integer(payload: JsonObject, key: str) -> int:
    value = nonnegative_integer(payload.get(key))
    if value is None:
        message = f"Luna reserve response is missing non-negative integer {key}"
        raise ValueError(message)
    return value


def _required_percentage(payload: JsonObject, key: str) -> float:
    value = _required_nonnegative_number(payload, key)
    if value > _MAXIMUM_PERCENT:
        message = f"Luna reserve response has out-of-range percentage {key}"
        raise ValueError(message)
    return value


def _optional_percentage(payload: JsonObject, key: str) -> float | None:
    if payload.get(key) is None:
        return None
    return _required_percentage(payload, key)
