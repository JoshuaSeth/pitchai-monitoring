# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deployment contract check for aggregate scheduling-capacity responses."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, cast

from .timeseries_types import optional_object, require_object

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
_SCHEMA_VERSION = 2


def validate_scheduling_capacity_payload(payload: JsonObject) -> None:
    """Reject malformed, identity-bearing, or secret-bearing scheduler data."""
    source = require_object(payload.get("source"), description="source")
    capacity = require_object(payload.get("capacity"), description="capacity")
    burn = require_object(payload.get("burn"), description="burn")
    token_burn = require_object(payload.get("token_burn"), description="token burn")
    banked_resets = require_object(payload.get("banked_resets"), description="banked resets")
    methodology = require_object(payload.get("methodology"), description="methodology")
    automatic_resets = payload.get("automatic_resets")
    expiry_buckets = payload.get("expiry_buckets")

    _require(condition=payload.get("schema_version") == _SCHEMA_VERSION, description="schema version")
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
        condition=capacity.get("measurement_status") in {"complete", "partial", "unavailable"},
        description="measurement status",
    )
    _require(
        condition=capacity.get("timeline_status") in {"complete", "partial", "unavailable"},
        description="timeline status",
    )
    _require(
        condition=burn.get("confidence") in {"high", "medium", "low", "unavailable"},
        description="burn confidence",
    )
    _require(condition=token_burn.get("diagnostic_only") is True, description="token burn role")
    _require(
        condition=banked_resets.get("included_as_automatic_capacity") is False,
        description="banked reset policy",
    )
    _require(
        condition=methodology.get("identity_scope") == "aggregate_only",
        description="identity scope",
    )
    reset_rows = _require_array(automatic_resets, description="automatic resets")
    expiry_rows = _require_array(expiry_buckets, description="expiry buckets")
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
