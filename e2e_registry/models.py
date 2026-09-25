# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared, concrete data contracts for the E2E registry."""

from __future__ import annotations

import json
from typing import NamedTuple, cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type DatabaseScalar = str | int | float | bytes | None
type DatabaseRecord = dict[str, DatabaseScalar]
type UntrustedJsonValue = JsonValue | bytes | bytearray | memoryview


class InvalidRegistryDataError(ValueError):
    """Raised when persisted or external registry data violates its contract."""


def require_json_object(value: UntrustedJsonValue, *, label: str) -> JsonObject:
    """Validate and return a JSON object.

    Args:
        value: Runtime value to validate.
        label: Human-readable source used in validation errors.

    Returns:
        The validated JSON object.

    Raises:
        InvalidRegistryDataError: If the value is not a JSON object.
    """
    if not isinstance(value, dict):
        message = f"{label} must be a JSON object"
        raise InvalidRegistryDataError(message)
    return value


def parse_json_object(
    value: UntrustedJsonValue,
    *,
    label: str,
    empty_when_missing: bool = False,
) -> JsonObject:
    """Decode and validate a persisted JSON object.

    Args:
        value: Serialized JSON text or an already decoded object.
        label: Human-readable source used in validation errors.
        empty_when_missing: Whether ``None`` and empty strings represent an empty object.

    Returns:
        A validated JSON object.

    Raises:
        InvalidRegistryDataError: If the value cannot be decoded as a JSON object.
    """
    if not value:
        if empty_when_missing:
            return {}
        message = f"{label} is missing"
        raise InvalidRegistryDataError(message)
    decoded = cast("UntrustedJsonValue", json.loads(value)) if isinstance(value, (str, bytes, bytearray)) else value
    return require_json_object(decoded, label=label)


def dump_json(value: JsonValue) -> str:
    """Serialize a validated JSON value deterministically.

    Returns:
        Stable JSON text suitable for persistence.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def require_text(
    value: UntrustedJsonValue,
    *,
    label: str,
    allow_empty: bool = False,
) -> str:
    """Return a validated text value.

    Raises:
        InvalidRegistryDataError: If the value is not permitted text.
    """
    if not isinstance(value, str):
        message = f"{label} must be text"
        raise InvalidRegistryDataError(message)
    if not allow_empty and not value.strip():
        message = f"{label} must not be empty"
        raise InvalidRegistryDataError(message)
    return value


def require_integer(value: UntrustedJsonValue, *, label: str) -> int:
    """Return a validated integer without truthiness coercion.

    Raises:
        InvalidRegistryDataError: If the value is not an integer representation.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        message = f"{label} must be an integer"
        raise InvalidRegistryDataError(message)
    text = str(value).strip()
    if not text or text.lstrip("-").isdigit() is False:
        message = f"{label} must be an integer"
        raise InvalidRegistryDataError(message)
    return int(text)


def require_float(value: UntrustedJsonValue, *, label: str) -> float:
    """Return a validated numeric value.

    Raises:
        InvalidRegistryDataError: If the value is not numeric.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        message = f"{label} must be numeric"
        raise InvalidRegistryDataError(message)
    text = str(value).strip()
    if not text:
        message = f"{label} must be numeric"
        raise InvalidRegistryDataError(message)
    return float(text)


class AuthedTenant(NamedTuple):
    """Tenant identity resolved from an API key."""

    tenant_id: str
    api_key_id: str


class ClaimedRun(NamedTuple):
    """One registry run whose lock is owned by a runner."""

    run_id: str
    test_id: str
    tenant_id: str
    test_name: str
    base_url: str
    timeout_seconds: int
    test_kind: str
    definition: JsonObject
    source_relpath: str | None
    source_filename: str | None
    source_sha256: str | None


class RunCompletion(NamedTuple):
    """Runner result submitted to the registry."""

    status: str
    elapsed_ms: float | None
    error_kind: str | None
    error_message: str | None
    final_url: str | None
    title: str | None
    artifacts: JsonObject
    started_at_ts: float | None
    finished_at_ts: float | None


class CompletionOutcome(NamedTuple):
    """State transition produced by an accepted run completion."""

    updated: bool
    alerted_down: bool
    recovered_up: bool
    effective_ok: bool | None
    fail_streak: int | None
    success_streak: int | None
    tenant_id: str | None
    test_id: str | None
    test_name: str | None
    run_id: str | None
