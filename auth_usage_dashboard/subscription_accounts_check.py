# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deployment contract check for subscription-account responses."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .subscription_accounts import ACCESS_STATES, SCHEMA_VERSION
from .timeseries_types import require_object

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

_FORBIDDEN_KEYS = (
    "auth_json",
    "access_token",
    "refresh_token",
    "admin_token",
)
_ACCOUNT_KEYS = {
    "email",
    "protected",
    "plan",
    "access_status",
    "access_state",
    "renewal_enabled",
    "cancellation_scheduled",
    "cancellation_requested_at",
    "access_ends_on",
    "renews_on",
    "verified_at",
    "verified_source",
    "verified_age_days",
    "verified_stale",
    "notes",
}


def validate_subscription_payload(payload: JsonObject) -> None:
    """Reject malformed or secret-bearing subscription data."""
    _require(
        condition=payload.get("schema_version") == SCHEMA_VERSION,
        description="schema version",
    )
    _require(
        condition=isinstance(payload.get("timezone"), str),
        description="timezone",
    )
    accounts = _require_array(payload.get("accounts"), description="accounts")
    for row in accounts:
        account = require_object(row, description="subscription account")
        _require(condition=set(account) == _ACCOUNT_KEYS, description="account fields")
        _require(
            condition=account.get("access_state") in ACCESS_STATES,
            description="access state",
        )
        email_text = account.get("email")
        _require(
            condition=isinstance(email_text, str) and email_text.count("@") == 1,
            description="login identity",
        )
    encoded = json.dumps(payload)
    forbidden_present = any(forbidden in encoded for forbidden in _FORBIDDEN_KEYS)
    _require(condition=not forbidden_present, description="secret fields")


def _require_source_agreement(payload: JsonObject, source_path: Path) -> None:
    """Require the served rows to match the installed source snapshot."""
    decoded = cast("JsonValue", json.loads(source_path.read_text(encoding="utf-8")))
    source = require_object(decoded, description="subscription source")
    source_accounts = _require_array(
        source.get("accounts"),
        description="source accounts",
    )
    served_accounts = _require_array(payload.get("accounts"), description="served accounts")
    _require(
        condition=len(served_accounts) == len(source_accounts),
        description="served account count",
    )


def _require(*, condition: bool, description: str) -> None:
    """Raise when one deployment-contract invariant is false.

    Raises:
        AssertionError: If the invariant is false.
    """
    if not condition:
        message = f"invalid subscription response {description}"
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
    message = f"subscription response {description} must be an array"
    raise TypeError(message)


def main() -> None:
    """Validate one JSON document from standard input."""
    decoded = cast("JsonValue", json.load(sys.stdin))
    payload = require_object(decoded, description="subscription response")
    validate_subscription_payload(payload)
    if len(sys.argv) > 1:
        _require_source_agreement(payload, Path(sys.argv[1]))


if __name__ == "__main__":
    main()
