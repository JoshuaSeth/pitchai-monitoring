# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deployment contract check for aggregate scheduling-capacity responses."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, cast

from .scheduling_capacity_timeline_values import aware_datetime
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    optional_object,
    require_object,
    text_value,
)

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

_FORBIDDEN_KEYS = (
    "auth_json",
    "access_token",
    "refresh_token",
    "admin_token",
    "credit_id",
)
_SOURCE_KEYS = {
    "stale",
    "error",
    "history_error",
    "newest_probe_at",
    "freshness_seconds",
}
_SCHEMA_VERSION = 4
_PROTECTED_KEYS = {
    "account_count",
    "reporting_accounts",
    "usable_accounts_now",
    "remaining_points",
    "maximum_known_points",
    "included_in_admission",
    "routing_owner",
    "burn_order",
    "classification_status",
    "unclassified_account_count",
}
_BURN_WINDOW_KEYS = {
    "window_hours",
    "starts_at",
    "ends_at",
    "capacity_points",
    "capacity_points_per_hour",
    "source",
    "confidence",
    "sample_count",
    "covered_accounts",
    "coverage_percent",
    "measured_hours",
    "provider_tokens",
    "token_covered_accounts",
}


def validate_scheduling_capacity_payload(payload: JsonObject) -> None:
    """Reject malformed, identity-bearing, or secret-bearing scheduler data."""
    source = require_object(payload.get("source"), description="source")
    capacity = require_object(payload.get("capacity"), description="capacity")
    protected = require_object(
        payload.get("protected_last_resort"),
        description="protected last-resort capacity",
    )
    burn = require_object(payload.get("burn"), description="burn")
    burn_windows = require_object(
        payload.get("burn_windows"),
        description="burn windows",
    )
    token_burn = require_object(payload.get("token_burn"), description="token burn")
    banked_resets = require_object(
        payload.get("banked_resets"),
        description="banked resets",
    )
    methodology = require_object(payload.get("methodology"), description="methodology")

    _require(
        condition=payload.get("schema_version") == _SCHEMA_VERSION,
        description="schema version",
    )
    _require(
        condition=payload.get("status") in {"available", "degraded", "unavailable"},
        description="status",
    )
    _require(condition=set(source) == _SOURCE_KEYS, description="source fields")
    _require(
        condition=capacity.get("basis_key") in {"five_hour", "weekly", None},
        description="capacity basis",
    )
    _require(
        condition=capacity.get("measurement_status")
        in {"complete", "partial", "unavailable"},
        description="measurement status",
    )
    _require(
        condition=capacity.get("timeline_status")
        in {"complete", "partial", "unavailable"},
        description="timeline status",
    )
    _require(
        condition=set(protected) == _PROTECTED_KEYS,
        description="protected fields",
    )
    _validate_protected_capacity(protected)
    _validate_burn_windows(burn_windows)
    _require(
        condition=burn.get("confidence") in {"high", "medium", "low", "unavailable"},
        description="burn confidence",
    )
    _require(
        condition=token_burn.get("diagnostic_only") is True,
        description="token burn role",
    )
    _require(
        condition=banked_resets.get("included_as_automatic_capacity") is False,
        description="banked reset policy",
    )
    _require(
        condition=methodology.get("identity_scope") == "aggregate_only",
        description="identity scope",
    )
    _require(
        condition=methodology.get("routing_tier_scope") == "broker_burnable",
        description="routing-tier scope",
    )
    _require(
        condition=methodology.get("protected_capacity_policy") == "broker_routes_last",
        description="protected capacity policy",
    )
    _require(
        condition=methodology.get("account_ordering_owner") == "authentication_broker",
        description="account ordering owner",
    )
    _require(
        condition=methodology.get("token_usage_role")
        == "project_attribution_denominator",
        description="token usage role",
    )
    reset_rows = _require_array(
        payload.get("automatic_resets"), description="automatic resets"
    )
    expiry_rows = _require_array(
        payload.get("expiry_buckets"), description="expiry buckets"
    )
    for event in reset_rows:
        _require(
            condition="account_label" not in optional_object(event),
            description="automatic reset identity",
        )
    for bucket in expiry_rows:
        _require(
            condition="account_label" not in optional_object(bucket),
            description="expiry bucket identity",
        )
    encoded = json.dumps(payload)
    _require(condition="@" not in encoded, description="email identity")
    forbidden_present = any(forbidden in encoded for forbidden in _FORBIDDEN_KEYS)
    _require(condition=not forbidden_present, description="secret fields")


def _validate_protected_capacity(protected: JsonObject) -> None:
    """Validate the informational last-resort routing aggregate."""
    _require(
        condition=protected.get("included_in_admission") is True,
        description="protected admission policy",
    )
    _require(
        condition=protected.get("routing_owner") == "authentication_broker",
        description="protected routing owner",
    )
    _require(
        condition=protected.get("burn_order") == "last_resort",
        description="protected burn order",
    )
    _require(
        condition=protected.get("classification_status")
        in {"complete", "partial", "unavailable"},
        description="protected classification status",
    )
    protected_account_count = nonnegative_integer(protected.get("account_count"))
    protected_reporting = nonnegative_integer(protected.get("reporting_accounts"))
    protected_usable = nonnegative_integer(protected.get("usable_accounts_now"))
    protected_remaining = number_value(protected.get("remaining_points"))
    protected_maximum = number_value(protected.get("maximum_known_points"))
    unclassified_count = nonnegative_integer(
        protected.get("unclassified_account_count"),
    )
    _require(
        condition=(
            protected_account_count is not None
            and protected_reporting is not None
            and protected_usable is not None
            and protected_usable <= protected_reporting <= protected_account_count
        ),
        description="protected account counts",
    )
    _require(
        condition=(protected_remaining is None) == (protected_maximum is None),
        description="protected point availability",
    )
    _require(
        condition=(
            protected_remaining is None
            or protected_maximum is None
            or (0.0 <= protected_remaining <= protected_maximum)
        ),
        description="protected point bounds",
    )
    _require(
        condition=unclassified_count is not None,
        description="unclassified account count",
    )


def _validate_burn_windows(burn_windows: JsonObject) -> None:
    """Validate bounded native-or-estimated burn evidence."""
    _require(
        condition=set(burn_windows) == {"last_hour", "last_24_hours"},
        description="burn window names",
    )
    for name, hours in (("last_hour", 1), ("last_24_hours", 24)):
        window = require_object(burn_windows.get(name), description=name)
        _require(
            condition=set(window) == _BURN_WINDOW_KEYS, description=f"{name} fields"
        )
        _require(
            condition=window.get("window_hours") == hours,
            description=f"{name} duration",
        )
        _require(
            condition=window.get("source")
            in {"native_broker_samples", "current_window_average"},
            description=f"{name} source",
        )
        _require(
            condition=window.get("confidence") in {"high", "medium", "low"},
            description=f"{name} confidence",
        )
        _validate_burn_window_values(window, name=name, hours=hours)


def _validate_burn_window_values(
    window: JsonObject,
    *,
    name: str,
    hours: int,
) -> None:
    """Validate one burn window's chronology, counters, and source claims."""
    starts_at = aware_datetime(text_value(window.get("starts_at")))
    ends_at = aware_datetime(text_value(window.get("ends_at")))
    _require(
        condition=(
            starts_at is not None
            and ends_at is not None
            and (ends_at - starts_at).total_seconds() == hours * 3600
        ),
        description=f"{name} chronology",
    )
    counters = (
        nonnegative_integer(window.get("sample_count")),
        nonnegative_integer(window.get("covered_accounts")),
        nonnegative_integer(window.get("token_covered_accounts")),
    )
    _require(
        condition=all(counter is not None for counter in counters),
        description=f"{name} counters",
    )
    coverage = number_value(window.get("coverage_percent"))
    _require(
        condition=coverage is not None and 0.0 <= coverage <= 100.0,
        description=f"{name} coverage",
    )
    points = number_value(window.get("capacity_points"))
    rate = number_value(window.get("capacity_points_per_hour"))
    measured = number_value(window.get("measured_hours"))
    _require(
        condition=(
            points is not None
            and points >= 0.0
            and rate is not None
            and rate >= 0.0
            and measured is not None
            and measured >= 0.0
        ),
        description=f"{name} burn values",
    )
    provider_tokens = window.get("provider_tokens")
    _require(
        condition=provider_tokens is None
        or nonnegative_integer(provider_tokens) is not None,
        description=f"{name} provider tokens",
    )
    if window.get("source") == "current_window_average":
        _require(
            condition=coverage == 0.0
            and measured == 0.0
            and provider_tokens is None,
            description=f"{name} estimated-source claims",
        )
    else:
        _require(
            condition=measured is not None and measured <= float(hours),
            description=f"{name} measured duration",
        )


def _require(*, condition: bool, description: str) -> None:
    """Raise when one deployment-contract invariant is false.

    Raises:
        AssertionError: If the invariant is false.
    """
    if not condition:
        message = f"invalid scheduling capacity {description}"
        raise AssertionError(message)


def _require_array(value: JsonValue, *, description: str) -> list[JsonValue]:
    """Require one JSON array in the deployment response.

    Returns:
        The narrowed JSON array.

    Raises:
        TypeError: If the value is not an array.
    """
    if isinstance(value, list):
        return value
    message = f"scheduling capacity {description} must be an array"
    raise TypeError(message)


def main() -> None:
    """Validate one JSON document from standard input."""
    decoded = cast("JsonValue", json.load(sys.stdin))
    payload = require_object(decoded, description="scheduling capacity response")
    validate_scheduling_capacity_payload(payload)


if __name__ == "__main__":
    main()
