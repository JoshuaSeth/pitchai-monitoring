# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build safe shared fixtures for guardian behavior tests."""

from __future__ import annotations

from datetime import UTC as DATETIME_UTC
from datetime import timedelta
from typing import TYPE_CHECKING, TypedDict

from auth_reset_guardian.models import utc_iso
from tests.auth_test_contract import FixtureContractError

if TYPE_CHECKING:
    from datetime import datetime

    from auth_reset_guardian.clients import JsonRequest
    from auth_reset_guardian.json_contract import JsonObject, JsonValue

UTC = DATETIME_UTC


class HttpCall(TypedDict):
    """Represent one captured guardian HTTP call."""

    method: str
    url: str
    endpoint: str
    headers: dict[str, str]
    payload: JsonObject | None
    ambiguous_on_failure: bool


class MutableClock:
    """Expose a deterministic mutable UTC clock."""

    def __init__(self, now: datetime) -> None:
        """Initialize the clock."""
        self.now: datetime = now

    def __call__(self) -> datetime:
        """Return the mutable current time."""
        return self.now

    def advance(self, duration: timedelta) -> None:
        """Advance the clock by one explicit duration."""
        self.now += duration


def capture_http_call(request_spec: JsonRequest) -> HttpCall:
    """Copy one strict request into the assertion-friendly call shape.

    Returns:
        The resulting value.

    """
    captured: HttpCall = {
        "method": request_spec.method,
        "url": request_spec.url,
        "endpoint": request_spec.endpoint,
        "headers": request_spec.headers,
        "payload": request_spec.payload,
        "ambiguous_on_failure": request_spec.ambiguous_on_failure,
    }
    return captured


def required_object(container: JsonObject, key: str) -> JsonObject:
    """Require one nested object in a simulation fixture.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If the fixture field is not an object.

    """
    value = container.get(key)
    if not isinstance(value, dict):
        msg = f"fixture field {key} must contain an object"
        raise FixtureContractError(msg)
    return value


def required_text(container: JsonObject, key: str) -> str:
    """Require one text value in a recursive JSON object.

    Returns:
        The resulting text.

    Raises:
        FixtureContractError: If the fixture field is not text.

    """
    value = container.get(key)
    if not isinstance(value, str):
        msg = f"fixture field {key} must contain text"
        raise FixtureContractError(msg)
    return value


def required_array(container: JsonObject, key: str) -> list[JsonValue]:
    """Require one mutable array in a simulation fixture.

    Returns:
        The resulting collection.

    Raises:
        FixtureContractError: If the fixture field is not an array.

    """
    value = container.get(key)
    if not isinstance(value, list):
        msg = f"fixture field {key} must contain an array"
        raise FixtureContractError(msg)
    return value


def required_array_object(values: list[JsonValue], index: int) -> JsonObject:
    """Require one object at an array index.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If the fixture array item is not an object.

    """
    value = values[index]
    if not isinstance(value, dict):
        msg = f"fixture array item {index} must contain an object"
        raise FixtureContractError(msg)
    return value


def append_consume_outcome(
    fixture: JsonObject,
    *,
    provider_id: str,
    outcome: JsonObject,
) -> None:
    """Append one provider result to a fixture's first account outcome queue."""
    accounts = required_array(fixture, "accounts")
    account = required_array_object(accounts, 0)
    outcomes = required_object(account, "consume_outcomes")
    provider_outcomes = required_array(outcomes, provider_id)
    provider_outcomes.append(outcome)


def credit_fixture(
    *,
    credit_id: str,
    expires_at: datetime,
    status: str = "available",
) -> JsonObject:
    """Build one provider-shaped reset-credit fixture.

    Returns:
        The resulting value.

    """
    return {
        "id": credit_id,
        "reset_type": "codex_rate_limits",
        "status": status,
        "granted_at": utc_iso(expires_at - timedelta(days=30)),
        "expires_at": utc_iso(expires_at),
        "title": "Full reset",
        "is_supported_by_plan": True,
    }


def guardian_fixture(
    *,
    expires_at: datetime,
    credit_id: str = "opaque-provider-credit",
    outcome: str = "nothing_to_reset",
) -> JsonObject:
    """Build one complete single-account guardian fixture.

    Returns:
        The resulting value.

    """
    return {
        "accounts": [
            {
                "label": "info@pitchai.net",
                "broker_availability": "available",
                "usage": {
                    "rate_limit": {
                        "allowed": True,
                        "limit_reached": False,
                        "primary_window": {
                            "limit_window_seconds": 604800,
                            "reset_after_seconds": 1200,
                            "reset_at": int(
                                (expires_at + timedelta(days=3)).timestamp(),
                            ),
                            "used_percent": 5,
                        },
                        "secondary_window": None,
                    },
                    "rate_limit_reset_credits": {
                        "available_count": 1,
                        "applicable_available_count": 0,
                    },
                },
                "credit_inventory": {
                    "available_count": 1,
                    "credits": [
                        credit_fixture(credit_id=credit_id, expires_at=expires_at),
                    ],
                },
                "consume_outcomes": {
                    credit_id: [
                        {
                            "code": outcome,
                            "windows_reset": 2 if outcome == "reset" else 0,
                        },
                    ],
                },
            },
        ],
    }
