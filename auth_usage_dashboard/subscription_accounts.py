# Copyright (c) 2026 PitchAI. All rights reserved.
"""Verified ChatGPT subscription state for the capacity dashboard.

Facts come only from signed-in billing-portal checks and the matching OpenAI
confirmation mail. Usage windows, reset credits, and broker routing flags never
change a subscription state here, and a cancelled auto-renewal keeps its paid
access until the verified period end.
"""

from __future__ import annotations

import json
import time
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .subscription_expiry import DEFAULT_TIMEZONE, subscription_end, subscription_timezone

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from .subscription_expiry import SubscriptionEnd
    from .timeseries_types import JsonObject, JsonValue

SCHEMA_VERSION = 1
SUBSCRIPTION_ACCOUNTS_FILE = Path("/dashboard-data/codex-subscriptions.json")
ACCESS_STATUSES = frozenset({"active", "inactive", "unknown"})
ACCESS_STATES = frozenset(
    {"renewing", "active_until_end", "access_ended", "inactive", "unknown"},
)
MAX_SNAPSHOT_BYTES = 131_072
MAX_ACCOUNTS = 64
MAX_TEXT_LENGTH = 240
MAX_VERIFIED_AGE_DAYS = 30
SECONDS_PER_DAY = 86_400
CONTROL_CHARACTER_LIMIT = 32
DELETE_CHARACTER_ORDINAL = 127
VISIBLE_ASCII_MINIMUM = 33
VISIBLE_ASCII_MAXIMUM = 126


def _clean_text(value: JsonValue) -> str | None:
    """Return collapsed printable text, or None when the value is unusable."""
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    if not collapsed or len(collapsed) > MAX_TEXT_LENGTH:
        return None
    unprintable = any(
        ord(character) < CONTROL_CHARACTER_LIMIT
        or ord(character) == DELETE_CHARACTER_ORDINAL
        for character in collapsed
    )
    return None if unprintable else collapsed


def _clean_email(value: JsonValue) -> str | None:
    """Return a lowercase single-address mail identity, or None when unusable."""
    text_value = _clean_text(value)
    if text_value is None or text_value.count("@") != 1:
        return None
    if not all(
        VISIBLE_ASCII_MINIMUM <= ord(character) <= VISIBLE_ASCII_MAXIMUM
        for character in text_value
    ):
        return None
    return text_value.lower()


def _flag(value: JsonValue) -> bool | None:
    """Return a tri-state flag, or None when the record does not state one."""
    return value if isinstance(value, bool) else None


def _calendar_date(value: JsonValue) -> date | None:
    """Return a calendar date, or None when the value is unusable."""
    text_value = _clean_text(value)
    parsed: date | None = None
    if text_value is not None:
        with suppress(ValueError):
            parsed = date.fromisoformat(text_value)
    return parsed


def _timestamp(value: JsonValue) -> datetime | None:
    """Return an offset-aware timestamp, or None when the value is unusable."""
    text_value = _clean_text(value)
    parsed: datetime | None = None
    if text_value is not None:
        with suppress(ValueError):
            parsed = datetime.fromisoformat(text_value)
    if parsed is None or parsed.tzinfo is None:
        return None
    return parsed


def _requested_at(value: JsonValue) -> str | None:
    """Return a cancellation moment as text, accepting date or timestamp form."""
    moment = _timestamp(value)
    if moment is not None:
        return moment.isoformat()
    day = _calendar_date(value)
    return day.isoformat() if day is not None else None


def _access_state(
    *,
    status: str,
    renewal: bool | None,
    end: SubscriptionEnd,
    now: datetime,
) -> str:
    """Derive the display state; cancelled access stays active until it ends.

    Returns:
        The explicit display state for one account row.
    """
    if status == "unknown" or end.precision == "invalid":
        return "unknown"
    if status == "inactive":
        return "inactive"
    if end.instant is not None:
        return "access_ended" if now >= end.instant else "renewing" if renewal is True else "active_until_end"
    if renewal is True:
        return "renewing"
    if end.day is None:
        return "unknown"
    return "access_ended" if end.day < now.date().isoformat() else "active_until_end"


def _account_row(raw: JsonValue, *, zone: ZoneInfo, now: float) -> JsonObject | None:
    """Normalize one stored account record into the explicit public shape.

    Returns:
        The public account row, or None when the record has no usable identity.
    """
    if not isinstance(raw, dict):
        return None
    email = _clean_email(raw.get("email"))
    if email is None:
        return None
    reported_status = raw.get("access_status")
    status = reported_status if isinstance(reported_status, str) and reported_status in ACCESS_STATUSES else "unknown"
    renewal = _flag(raw.get("renewal_enabled"))
    end = subscription_end(raw, zone=zone)
    renews_on = _calendar_date(raw.get("renews_on"))
    verified = _timestamp(raw.get("verified_at"))
    age_days = max(0, int((now - verified.timestamp()) // SECONDS_PER_DAY)) if verified is not None else None
    return {
        "email": email,
        "protected": raw.get("protected") is True,
        "plan": _clean_text(raw.get("plan")),
        "access_status": status,
        "access_state": _access_state(
            status=status,
            renewal=renewal,
            end=end,
            now=datetime.fromtimestamp(now, zone),
        ),
        "renewal_enabled": renewal,
        "cancellation_scheduled": _flag(raw.get("cancellation_scheduled")),
        "cancellation_requested_at": _requested_at(raw.get("cancellation_requested_at")),
        "access_ends_on": end.day,
        "access_ends_at": end.instant.isoformat() if end.instant is not None else None,
        "access_end_precision": end.precision,
        "renews_on": renews_on.isoformat() if renews_on is not None else None,
        "verified_at": verified.isoformat() if verified is not None else None,
        "verified_source": _clean_text(raw.get("verified_source")),
        "verified_age_days": age_days,
        "verified_stale": age_days is None or age_days > MAX_VERIFIED_AGE_DAYS or (
            verified is not None and verified.timestamp() > now
        ),
        "notes": _clean_text(raw.get("notes")),
    }


def _load_document(path: Path) -> JsonValue | None:
    """Read one bounded JSON document.

    Returns:
        The decoded document, or None when it cannot be used.
    """
    document: JsonValue | None = None
    with suppress(OSError, ValueError):
        if path.stat().st_size <= MAX_SNAPSHOT_BYTES:
            document = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    return document


def read_snapshot(path: Path, *, now: float | None = None) -> JsonObject:
    """Return the dashboard-facing subscription snapshot as an explicit schema.

    Returns:
        A JSON-ready object; an unreadable or invalid snapshot yields an error
        state instead of invented accounts or dates.
    """
    current = time.time() if now is None else now
    document = _load_document(path)
    rows = document.get("accounts") if isinstance(document, dict) else None
    document_timezone = document.get("timezone") if isinstance(document, dict) else None
    zone = subscription_timezone(document_timezone)
    generated_at = _timestamp(document.get("generated_at")) if isinstance(document, dict) else None
    valid = isinstance(document, dict) and document.get("schema_version") == SCHEMA_VERSION and isinstance(rows, list)
    accounts: list[JsonValue] = []
    if valid and isinstance(rows, list) and zone is not None:
        for raw in rows[:MAX_ACCOUNTS]:
            account = _account_row(raw, zone=zone, now=current)
            if account is not None:
                accounts.append(account)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat() if generated_at is not None else None,
        "timezone": zone.key if zone is not None else _clean_text(document_timezone) or DEFAULT_TIMEZONE,
        "accounts": accounts,
        "error": "Subscription timezone is unsupported" if zone is None else (
            None if accounts else "Subscription status is unavailable"
        ),
    }
