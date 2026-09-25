# Copyright (c) 2026 PitchAI. All rights reserved.
"""Sanitize broker/provider payloads before guardian orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .model_values import utc_now
from .models import PayloadError, ResetCredit

_MAX_RESET_CREDITS = 1000

if TYPE_CHECKING:
    from .json_contract import JsonObject, JsonValue


def sanitize_broker_state(payload: JsonObject) -> JsonObject:
    """Return the bounded broker state needed for audit and decisions.

    Raises:
        PayloadError: If provider data violates the payload contract.

    """
    state = payload.get("state")
    if not isinstance(state, dict):
        msg = "broker analytics probe is missing state"
        raise PayloadError(msg)
    analytics = state.get("analytics")
    analytics = analytics if isinstance(analytics, dict) else {}
    raw_errors = analytics.get("errors")
    errors: JsonObject = {}
    if isinstance(raw_errors, dict):
        for key, value in raw_errors.items():
            errors[str(key)[:80]] = str(value)[:80]
    return {
        "availability": optional_text(state.get("availability"), 80),
        "last_probe_at": optional_text(state.get("last_probe_at"), 80),
        "cooldown_until": optional_text(state.get("cooldown_until"), 80),
        "analytics_last_probe_at": optional_text(analytics.get("last_probe_at"), 80),
        "analytics_errors": errors,
    }


def sanitize_usage(payload: JsonObject) -> JsonObject:
    """Return the bounded provider usage fields used by the guardian.

    Raises:
        PayloadError: If provider data violates the payload contract.

    """
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        msg = "provider usage response is missing rate_limit"
        raise PayloadError(msg)
    reset_summary = payload.get("rate_limit_reset_credits")
    reset_summary = reset_summary if isinstance(reset_summary, dict) else {}
    return {
        "allowed": bool(rate_limit.get("allowed", False)),
        "limit_reached": bool(rate_limit.get("limit_reached", False)),
        "primary_window": _sanitize_window(rate_limit.get("primary_window")),
        "secondary_window": _sanitize_window(rate_limit.get("secondary_window")),
        "available_reset_count": optional_nonnegative_int(
            reset_summary.get("available_count"),
        ),
        "applicable_reset_count": optional_nonnegative_int(
            reset_summary.get("applicable_available_count"),
        ),
    }


def _sanitize_window(value: JsonValue) -> JsonObject | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        msg = "provider rate-limit window must be an object or null"
        raise PayloadError(msg)
    result: JsonObject = {}
    for key in (
        "limit_window_seconds",
        "reset_after_seconds",
        "reset_at",
        "used_percent",
    ):
        parsed = optional_nonnegative_int(value.get(key))
        if parsed is not None:
            result[key] = parsed
    return result


def parse_credit_inventory(payload: JsonObject) -> tuple[int, tuple[ResetCredit, ...]]:
    """Parse and order one bounded provider reset-credit inventory.

    Returns:
        The resulting collection.

    Raises:
        PayloadError: If provider data violates the payload contract.

    """
    available_count = optional_nonnegative_int(payload.get("available_count"))
    if available_count is None:
        msg = "provider reset-credit response is missing available_count"
        raise PayloadError(msg)
    raw_credits = payload.get("credits")
    if not isinstance(raw_credits, list):
        msg = "provider reset-credit response is missing credits"
        raise PayloadError(msg)
    if len(raw_credits) > _MAX_RESET_CREDITS:
        msg = "provider reset-credit response exceeds the safety limit"
        raise PayloadError(msg)
    reset_credits = tuple(ResetCredit.from_provider(raw) for raw in raw_credits)
    refs = [credit.credit_ref for credit in reset_credits]
    if len(refs) != len(set(refs)):
        msg = "provider reset-credit response contains duplicate IDs"
        raise PayloadError(msg)
    ordered = sorted(
        reset_credits,
        key=lambda credit: (
            credit.expires_at is None,
            credit.expires_at or datetime.max.replace(tzinfo=utc_now().tzinfo),
        ),
    )
    return available_count, tuple(ordered)


def optional_nonnegative_int(value: JsonValue) -> int | None:
    """Return a nonnegative integer or preserve absence as unknown."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def optional_text(value: JsonValue, limit: int) -> str | None:
    """Return bounded nonblank text or preserve absence."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]
