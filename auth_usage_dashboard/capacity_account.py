# Copyright (c) 2026 PitchAI. All rights reserved.
"""Classify one broker account's selectability from its redacted state files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, TypedDict

from .capacity_credits import AnalyticsFreshness, reset_credits, token_usage
from .capacity_values import bounded_integer, isoformat, parse_timestamp
from .capacity_windows import account_windows
from .timeseries_types import number_value, optional_object, text_value
from .usage_credits import usage_credits

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from typing import Unpack

    from .timeseries_types import JsonObject, JsonValue

_DEFAULT_ANALYTICS_STALE_AFTER_SECONDS = 1800


class AccountOptions(TypedDict):
    """Keyword options accepted by :func:`parse_account`."""

    now: datetime
    stale_after_seconds: int
    min_five_hour_remaining_percent: float
    analytics_stale_after_seconds: NotRequired[int]
    probe_error: NotRequired[str | None]
    analytics_probe_error: NotRequired[str | None]


@dataclass(frozen=True)
class _QuotaWindow:
    """Selectability facts read back from one rendered quota window."""

    reported: bool
    remaining: float | None
    reset_due: bool

    @classmethod
    def read(cls, window: JsonObject, *, now: datetime) -> _QuotaWindow:
        """Read whether a rendered window is reported, how much remains, and if its reset is due.

        Returns:
            The window facts that drive account selectability.
        """
        reset_at = parse_timestamp(window.get("reset_at"))
        return cls(
            reported=window.get("reported") is True,
            remaining=number_value(window.get("remaining_percent")),
            reset_due=reset_at is not None and reset_at <= now,
        )

    @property
    def exhausted(self) -> bool:
        """Return whether the window is used up and its reset is still in the future."""
        return self.remaining is not None and self.remaining <= 0 and not self.reset_due


@dataclass(frozen=True)
class _Signals:
    """Every fact the broker status precedence depends on."""

    enabled: bool
    availability: str
    has_usage: bool
    credit_usable: bool
    at_safety_floor: bool
    five_hour: _QuotaWindow
    weekly: _QuotaWindow


def parse_account(raw: JsonObject, **options: Unpack[AccountOptions]) -> Mapping[str, JsonValue]:
    """Normalize one broker account into the dashboard's selectability record.

    Returns:
        Status, quota windows, analytics, credits, and freshness for the account.
    """
    now = options["now"]
    state = optional_object(raw.get("state"))
    usage = optional_object(state.get("usage"))
    last_probe = parse_timestamp(state.get("last_probe_at"))
    stale_seconds = None if last_probe is None else max(0, int((now - last_probe).total_seconds()))
    stale = stale_seconds is None or stale_seconds > options["stale_after_seconds"]
    credit_status = usage_credits(usage)
    paid_credits: JsonObject = {
        "balance": credit_status["balance"],
        "unlimited": credit_status["unlimited"],
        "usable": credit_status["usable"],
        "reason": credit_status["reason"],
        "stale": stale,
        "updated_at": isoformat(last_probe),
    }
    selection = _selection(
        optional_object(raw.get("metadata")),
        state,
        usage,
        options,
        credit_usable=credit_status["usable"] and not stale,
    )
    analytics = optional_object(state.get("analytics"))
    freshness = AnalyticsFreshness(
        now=now,
        stale_after_seconds=options.get("analytics_stale_after_seconds", _DEFAULT_ANALYTICS_STALE_AFTER_SECONDS),
        probe_error=options.get("analytics_probe_error"),
        errors=optional_object(analytics.get("errors")),
    )
    return {
        **selection,
        "token_usage": token_usage(analytics, freshness),
        "reset_credits": reset_credits(analytics, usage, freshness, last_probe=last_probe, probe_stale=stale),
        "usage_credits": paid_credits,
        "active_session_count": bounded_integer(state.get("active_session_count"), minimum=0) or 0,
        "latest_session_expires_at": isoformat(parse_timestamp(state.get("lease_expires_at"))),
        "last_probe_at": isoformat(last_probe),
        "stale": stale,
        "stale_seconds": stale_seconds,
        "probe_error": options.get("probe_error"),
    }


def _selection(
    metadata: JsonObject,
    state: JsonObject,
    usage: JsonObject,
    options: AccountOptions,
    *,
    credit_usable: bool,
) -> JsonObject:
    now = options["now"]
    label = text_value(metadata.get("label")) or "Unlabeled account"
    availability = text_value(state.get("availability")) or "unknown"
    five_hour, weekly = account_windows(usage, now=now)
    five_hour_window = _QuotaWindow.read(five_hour, now=now)
    at_safety_floor = (
        availability == "available"
        and not credit_usable
        and five_hour_window.remaining is not None
        and five_hour_window.remaining <= options["min_five_hour_remaining_percent"]
    )
    signals = _Signals(
        enabled=metadata.get("enabled", True) is not False,
        availability=availability,
        has_usage=bool(usage),
        credit_usable=credit_usable,
        at_safety_floor=at_safety_floor,
        five_hour=five_hour_window,
        weekly=_QuotaWindow.read(weekly, now=now),
    )
    status, reason = _status(signals)
    return {
        "label": label,
        "email": text_value(usage.get("email")) or label,
        "enabled": signals.enabled,
        "routing_preferred": metadata.get("prefer_for_all_clients") is True,
        "plan_type": text_value(usage.get("plan_type")),
        "status": status,
        "status_reason": reason,
        "availability": availability,
        "auth_valid": _auth_valid(availability, has_usage=signals.has_usage),
        "selectable_now": status == "available",
        "selection_blocked": status != "available",
        "safety_floor_active": at_safety_floor,
        "five_hour": five_hour,
        "weekly": weekly,
    }


def _status(signals: _Signals) -> tuple[str, str]:
    availability = signals.availability
    rate_limited = availability == "rate_limited"
    reset_due = signals.five_hour.reset_due or signals.weekly.reset_due
    precedence = (
        (not signals.enabled, "disabled", "Disabled in broker inventory"),
        (availability == "auth_invalid", "auth_invalid", "Login or token refresh required"),
        (not signals.has_usage or availability == "unknown", "unknown", "Usage state unavailable"),
        (
            signals.credit_usable and availability == "available",
            "available",
            "Selectable now; credits available beyond included usage",
        ),
        (signals.weekly.exhausted, "weekly_limited", "Weekly usage window exhausted"),
        (signals.five_hour.exhausted, "five_hour_limited", "Five-hour usage window exhausted"),
        (signals.at_safety_floor, "five_hour_limited", "Held at broker five-hour safety floor"),
        (rate_limited and reset_due, "unknown", "Reset is due; awaiting a fresh provider state"),
        (rate_limited and signals.five_hour.reported, "five_hour_limited", "Five-hour usage window limited"),
        (rate_limited, "unknown", "Provider reported a limit without a five-hour window"),
        (availability == "available", "available", "Selectable now"),
    )
    for matched, status, reason in precedence:
        if matched:
            return status, reason
    return "unknown", "Unrecognized broker availability"


def _auth_valid(availability: str, *, has_usage: bool) -> bool | None:
    if availability == "auth_invalid":
        return False
    if availability in {"available", "rate_limited"} or has_usage:
        return True
    return None
