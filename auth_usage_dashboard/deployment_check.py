# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validate deployment-facing capacity payload privacy and schema rules."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Final

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


type DocumentDecoder = Callable[[str], JsonValue]


def _document_decoder() -> DocumentDecoder:
    """Constrain the standalone decoder to deployment JSON values.

    Returns:
        The resulting value.

    """
    decoder: DocumentDecoder = json.loads
    return decoder


decode_document: Final[DocumentDecoder] = _document_decoder()

CAPACITY_SCHEMA_VERSION = 4
HISTORY_POINT_COUNT = 168
RUNOUT_HORIZON_COUNT = 3

FORBIDDEN_KEYS = (
    "auth_json",
    "access_token",
    "refresh_token",
    "admin_token",
    "credit_id",
)


class DeploymentPayloadError(AssertionError):
    """A deployment payload violated the published dashboard contract."""


def validate_capacity_payload(payload: JsonObject) -> None:
    """Validate the public capacity schema and privacy contract."""
    _require(
        condition=payload.get("schema_version") == CAPACITY_SCHEMA_VERSION,
        message="capacity schema version must be 4",
    )
    _validate_summary(payload)
    _validate_accounts(payload)
    _validate_history(payload)
    _validate_runout(payload)
    _validate_privacy(payload)


def _validate_summary(payload: JsonObject) -> None:
    summary = _required_object(payload, "summary")
    configured_accounts = summary.get("configured_accounts")
    _require(
        condition=isinstance(configured_accounts, int) and configured_accounts > 0,
        message="capacity payload must contain configured accounts",
    )
    basis = _required_object(summary, "capacity_basis")
    _require(
        condition=basis.get("key") in {"five_hour", "weekly", None},
        message="capacity basis key is unsupported",
    )
    _require_measurement_status(basis.get("measurement_status"))
    window_aggregates = _required_object(summary, "window_aggregates")
    for key in ("five_hour", "weekly"):
        aggregate = _required_object(window_aggregates, key)
        _require_measurement_status(aggregate.get("measurement_status"))


def _validate_accounts(payload: JsonObject) -> None:
    for account_value in _required_list(payload, "accounts"):
        if not isinstance(account_value, dict):
            msg = "capacity account must be an object"
            raise DeploymentPayloadError(msg)
        five_hour = _required_object(account_value, "five_hour")
        weekly = _required_object(account_value, "weekly")
        _require(
            condition=isinstance(five_hour.get("reported"), bool),
            message="five-hour flag must be boolean",
        )
        _require(
            condition=isinstance(weekly.get("reported"), bool),
            message="weekly flag must be boolean",
        )


def _validate_history(payload: JsonObject) -> None:
    usage_history = _required_object(payload, "usage_history")
    _require(
        condition=usage_history.get("provider_granularity") == "daily",
        message="provider history granularity must be daily",
    )
    _require(
        condition=usage_history.get("granularity") == "hour",
        message="history granularity must be hourly",
    )
    _require(
        condition=usage_history.get("point_count") == HISTORY_POINT_COUNT,
        message="history must contain 168 points",
    )
    _require(
        condition="combined" in usage_history,
        message="history must contain its combined series",
    )


def _validate_runout(payload: JsonObject) -> None:
    runout_forecast = _required_object(payload, "runout_forecast")
    _require(
        condition=(len(_required_list(runout_forecast, "horizons")) == RUNOUT_HORIZON_COUNT),
        message="runout forecast must contain three horizons",
    )
    reset_policy = _required_object(runout_forecast, "banked_reset_policy")
    _require(
        condition=reset_policy.get("included_as_automatic_capacity") is False,
        message="banked resets must not be automatic capacity",
    )
    reset_bank = _required_object(payload, "reset_bank")
    _require(
        condition="details" in reset_bank,
        message="reset bank must include details",
    )


def _validate_privacy(payload: JsonObject) -> None:
    encoded = json.dumps(payload)
    forbidden_key_present = False
    for forbidden_key in FORBIDDEN_KEYS:
        if forbidden_key in encoded:
            forbidden_key_present = True
            break
    _require(
        condition=not forbidden_key_present,
        message="capacity payload contains a forbidden secret-bearing key",
    )


def main() -> None:
    """Validate one capacity payload read from standard input.

    Raises:
        DeploymentPayloadError: If the payload violates the deployment contract.

    """
    payload = decode_document(sys.stdin.read())
    if not isinstance(payload, dict):
        msg = "capacity response must be an object"
        raise DeploymentPayloadError(msg)
    validate_capacity_payload(payload)


def _required_object(container: JsonObject, key: str) -> JsonObject:
    """Read one required object from a deployment payload.

    Returns:
        The resulting value.

    Raises:
        DeploymentPayloadError: If the field violates the deployment contract.

    """
    value = container.get(key)
    if not isinstance(value, dict):
        msg = f"capacity field {key} must be an object"
        raise DeploymentPayloadError(msg)
    return value


def _required_list(container: JsonObject, key: str) -> list[JsonValue]:
    """Read one required list from a deployment payload.

    Returns:
        The resulting collection.

    Raises:
        DeploymentPayloadError: If the field violates the deployment contract.

    """
    value = container.get(key)
    if not isinstance(value, list):
        msg = f"capacity field {key} must be a list"
        raise DeploymentPayloadError(msg)
    return value


def _require_measurement_status(value: JsonValue) -> None:
    """Validate one aggregate measurement status."""
    _require(
        condition=value in {"complete", "partial", "unavailable"},
        message="capacity measurement status is unsupported",
    )


def _require(*, condition: bool, message: str) -> None:
    """Raise a deployment assertion with one stable explanation.

    Raises:
        DeploymentPayloadError: If the payload violates the deployment contract.

    """
    if not condition:
        raise DeploymentPayloadError(message)


if __name__ == "__main__":
    main()
