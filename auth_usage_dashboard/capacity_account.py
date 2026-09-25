# Copyright (c) 2026 PitchAI. All rights reserved.
"""Normalize one broker observation into a redacted capacity account."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict, Unpack

from .capacity_account_status import (
    StatusInputs,
    account_auth_valid,
    classify_account_status,
)
from .capacity_analytics import parse_reset_credits, parse_token_usage
from .capacity_windows import named_rate_limit_windows, parse_window
from .value_parsing import integer, object_value, optional_isoformat, parse_datetime, string

if TYPE_CHECKING:
    from datetime import datetime

    from .capacity_account_status import (
        AccountStatus,
    )
    from .json_contract import JsonObject
    from .models import CapacityAccount, CapacityWindow, ResetCreditState


class AccountParseArguments(TypedDict):
    """Declare the keyword contract accepted by account parsing."""

    now: datetime
    stale_after_seconds: int
    min_five_hour_remaining_percent: float
    analytics_stale_after_seconds: NotRequired[int]
    probe_error: NotRequired[str | None]
    analytics_probe_error: NotRequired[str | None]


class ParseSettings(NamedTuple):
    """Hold normalized parsing thresholds and boundary errors."""

    now: datetime
    stale_after_seconds: int
    minimum_remaining: float
    analytics_stale_after_seconds: int
    probe_error: str | None
    analytics_probe_error: str | None


class AccountContext(NamedTuple):
    """Hold safe nested broker objects used during parsing."""

    metadata: JsonObject
    state: JsonObject
    usage: JsonObject
    analytics: JsonObject
    analytics_errors: JsonObject


class AccountFreshness(NamedTuple):
    """Represent the age of the broker account observation."""

    last_probe: datetime | None
    stale_seconds: int | None
    stale: bool


class AccountCore(NamedTuple):
    """Bundle normalized fields shared by the account payload."""

    label: str
    email: str
    enabled: bool
    routing_preferred: bool
    availability: str
    five_hour: CapacityWindow
    weekly: CapacityWindow
    freshness: AccountFreshness
    status: AccountStatus
    auth_valid: bool | None


def parse_account(
    raw: JsonObject,
    **arguments: Unpack[AccountParseArguments],
) -> CapacityAccount:
    """Parse one broker observation without exposing credentials or identifiers.

    Returns:
        The resulting value.

    """
    settings = _parse_settings(arguments)
    context = _account_context(raw)
    core = _account_core(context, settings=settings)
    token_usage = parse_token_usage(
        context.analytics.get("token_usage"),
        updated_at=context.analytics.get("token_usage_updated_at"),
        now=settings.now,
        stale_after_seconds=settings.analytics_stale_after_seconds,
        probe_error=settings.analytics_probe_error or string(context.analytics_errors.get("token_usage")),
    )
    reset_state = _account_credits(
        context,
        settings=settings,
        freshness=core.freshness,
    )
    return {
        "label": core.label,
        "email": core.email,
        "enabled": core.enabled,
        "routing_preferred": core.routing_preferred,
        "plan_type": string(context.usage.get("plan_type")),
        "status": core.status.value,
        "status_reason": core.status.reason,
        "availability": core.availability,
        "auth_valid": core.auth_valid,
        "selectable_now": core.status.value == "available",
        "selection_blocked": core.status.value != "available",
        "safety_floor_active": core.status.safety_floor,
        "five_hour": core.five_hour,
        "weekly": core.weekly,
        "token_usage": token_usage,
        "reset_credits": reset_state,
        "active_session_count": integer(
            context.state.get("active_session_count"),
            minimum=0,
        )
        or 0,
        "latest_session_expires_at": optional_isoformat(
            parse_datetime(context.state.get("lease_expires_at")),
        ),
        "last_probe_at": optional_isoformat(core.freshness.last_probe),
        "stale": core.freshness.stale,
        "stale_seconds": core.freshness.stale_seconds,
        "probe_error": settings.probe_error,
    }


def _parse_settings(arguments: AccountParseArguments) -> ParseSettings:
    return ParseSettings(
        arguments["now"],
        arguments["stale_after_seconds"],
        arguments["min_five_hour_remaining_percent"],
        arguments.get("analytics_stale_after_seconds", 1800),
        arguments.get("probe_error"),
        arguments.get("analytics_probe_error"),
    )


def _account_context(raw: JsonObject) -> AccountContext:
    metadata = object_value(raw, "metadata")
    state = object_value(raw, "state")
    usage = object_value(state, "usage")
    analytics = object_value(state, "analytics")
    return AccountContext(
        metadata,
        state,
        usage,
        analytics,
        object_value(analytics, "errors"),
    )


def _account_core(context: AccountContext, *, settings: ParseSettings) -> AccountCore:
    label = string(context.metadata.get("label")) or "Unlabeled account"
    availability = string(context.state.get("availability")) or "unknown"
    named_windows = named_rate_limit_windows(object_value(context.usage, "rate_limit"))
    five_hour = parse_window(
        named_windows["five_hour"],
        now=settings.now,
        default_seconds=18_000,
    )
    weekly = parse_window(
        named_windows["weekly"],
        now=settings.now,
        default_seconds=604_800,
    )
    freshness = _freshness(
        context.state,
        now=settings.now,
        stale_after_seconds=settings.stale_after_seconds,
    )
    enabled = context.metadata.get("enabled", True) is not False
    status = classify_account_status(
        StatusInputs(
            enabled,
            bool(context.usage),
            availability,
            five_hour,
            weekly,
            settings.now,
            settings.minimum_remaining,
        ),
    )
    return AccountCore(
        label,
        string(context.usage.get("email")) or label,
        enabled,
        context.metadata.get("prefer_for_all_clients") is True,
        availability,
        five_hour,
        weekly,
        freshness,
        status,
        account_auth_valid(availability, usage_available=bool(context.usage)),
    )


def _freshness(
    state: JsonObject,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> AccountFreshness:
    last_probe = parse_datetime(state.get("last_probe_at"))
    stale_seconds = None if last_probe is None else max(0, int((now - last_probe).total_seconds()))
    stale = last_probe is None or (stale_seconds is not None and stale_seconds > stale_after_seconds)
    return AccountFreshness(last_probe, stale_seconds, stale)


def _account_credits(
    context: AccountContext,
    *,
    settings: ParseSettings,
    freshness: AccountFreshness,
) -> ResetCreditState:
    analytics_credits = context.analytics.get("reset_credits")
    if isinstance(analytics_credits, dict):
        reset_state = parse_reset_credits(analytics_credits)
        updated_at = parse_datetime(context.analytics.get("reset_credits_updated_at"))
        reset_state["source"] = "provider_reset_inventory"
        reset_state["updated_at"] = optional_isoformat(updated_at)
        reset_state["stale"] = (
            updated_at is None or (settings.now - updated_at).total_seconds() > settings.analytics_stale_after_seconds
        )
    else:
        reset_state = parse_reset_credits(
            context.usage.get("rate_limit_reset_credits"),
        )
        reset_state["source"] = "usage_summary"
        reset_state["updated_at"] = optional_isoformat(freshness.last_probe)
        reset_state["stale"] = freshness.stale
    reset_state["probe_error"] = settings.analytics_probe_error or string(
        context.analytics_errors.get("reset_credits"),
    )
    return reset_state
