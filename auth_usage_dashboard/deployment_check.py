# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validate the redacted capacity response served by a freshly deployed dashboard.

The deployment script pipes ``/api/v1/capacity`` into this file with the host's
system ``python3`` (3.10), so it stays standalone and standard-library only.
Malformed shapes fail with the same exception types plain indexing would raise.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

FORBIDDEN_KEYS = (
    "auth_json",
    "access_token",
    "refresh_token",
    "admin_token",
    "credit_id",
)
_SCHEMA_VERSION = 4
_HOURLY_HISTORY_POINTS = 168
_RUNOUT_HORIZON_COUNT = 3
_CAPACITY_BASIS_KEYS = frozenset({"five_hour", "weekly", None})
_MEASUREMENT_STATUSES = frozenset({"complete", "partial", "unavailable"})


def validate_capacity_payload(payload: JsonObject) -> None:
    """Require the schema-four capacity contract without any secret-bearing key names.

    A wrong contract value or a forbidden key name fails with ``AssertionError``.
    """
    _require(holds=_field(payload, "schema_version") == _SCHEMA_VERSION)
    summary = _field(payload, "summary")
    _require(holds=_is_positive(_field(summary, "configured_accounts")))
    basis = _field(summary, "capacity_basis")
    _require(holds=_field(basis, "key") in _CAPACITY_BASIS_KEYS)
    _require(holds=_field(basis, "measurement_status") in _MEASUREMENT_STATUSES)
    for key in ("five_hour", "weekly"):
        aggregate = _field(_field(summary, "window_aggregates"), key)
        _require(holds=_field(aggregate, "measurement_status") in _MEASUREMENT_STATUSES)
    for account in _members(_field(payload, "accounts")):
        _require(holds=isinstance(_field(_field(account, "five_hour"), "reported"), bool))
        _require(holds=isinstance(_field(_field(account, "weekly"), "reported"), bool))
    history = _field(payload, "usage_history")
    _require(holds=_field(history, "provider_granularity") == "daily")
    _require(holds=_field(history, "granularity") == "hour")
    _require(holds=_field(history, "point_count") == _HOURLY_HISTORY_POINTS)
    _require(holds=_contains(history, "combined"))
    forecast = _field(payload, "runout_forecast")
    _require(holds=_length(_field(forecast, "horizons")) == _RUNOUT_HORIZON_COUNT)
    banked_policy = _field(forecast, "banked_reset_policy")
    _require(holds=_field(banked_policy, "included_as_automatic_capacity") is False)
    _require(holds=_contains(_field(payload, "reset_bank"), "details"))
    encoded = json.dumps(payload)
    leaked = any(forbidden in encoded for forbidden in FORBIDDEN_KEYS)
    _require(holds=not leaked)


def main() -> None:
    """Validate one capacity response read from standard input.

    Raises:
        AssertionError: If the response is not a JSON object or violates the contract.
    """
    payload = cast("JsonValue", json.load(sys.stdin))
    if isinstance(payload, dict):
        validate_capacity_payload(payload)
        return
    message = "capacity response must be an object"
    raise AssertionError(message)


def _require(*, holds: bool) -> None:
    if not holds:
        raise AssertionError


def _field(container: JsonValue, key: str) -> JsonValue:
    if isinstance(container, dict):
        return container[key]
    message = f"{type(container).__name__} capacity value has no field {key!r}"
    raise TypeError(message)


def _members(value: JsonValue) -> list[JsonValue]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict | str):
        return [*value]
    message = f"{type(value).__name__} capacity value is not iterable"
    raise TypeError(message)


def _contains(container: JsonValue, member: str) -> bool:
    if isinstance(container, dict | list | str):
        return member in container
    message = f"{type(container).__name__} capacity value is not a container"
    raise TypeError(message)


def _length(value: JsonValue) -> int:
    if isinstance(value, dict | list | str):
        return len(value)
    message = f"{type(value).__name__} capacity value has no length"
    raise TypeError(message)


def _is_positive(value: JsonValue) -> bool:
    if isinstance(value, int | float):
        return value > 0
    message = f"{type(value).__name__} capacity value is not a number"
    raise TypeError(message)


if __name__ == "__main__":
    main()
