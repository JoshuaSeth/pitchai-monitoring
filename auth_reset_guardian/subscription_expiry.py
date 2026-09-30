# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read reviewed subscription end dates without inferring billing from quota."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast
from zoneinfo import ZoneInfo

from .models import PayloadError, parse_timestamp, utc_iso

if TYPE_CHECKING:
    from .models import AccountObservation

SUBSCRIPTION_FILE = Path("/srv/codex-usage-dashboard/codex-subscriptions.json")
MAX_VERIFIED_AGE = timedelta(days=30)
MAX_SNAPSHOT_BYTES = 131_072


class SubscriptionDocument(TypedDict):
    """Unvalidated fields at the reviewed subscription JSON boundary."""

    schema_version: object
    timezone: object
    accounts: object


class SubscriptionCutoff(TypedDict):
    """Unvalidated exact entitlement cutoff from the reviewed snapshot."""

    access_ends_at: object


def read_subscription_expiry(label: str, *, now: datetime) -> dict[str, str | None]:
    """Read one exact account's reviewed end date at the filesystem IO edge.

    Returns:
        Only the subscription date and provenance needed for ordering and audit.

    Raises:
        PayloadError: The installed snapshot is malformed or ambiguous.
    """
    if not SUBSCRIPTION_FILE.exists():
        return {"subscription_access_ends_on": None}
    with SUBSCRIPTION_FILE.open("rb") as stream:
        raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
    if len(raw) > MAX_SNAPSHOT_BYTES:
        message = "subscription snapshot exceeds its size limit"
        raise PayloadError(message)
    document = cast("object", json.loads(raw))
    if not isinstance(document, dict):
        message = "subscription snapshot must be an object"
        raise PayloadError(message)
    fields = cast("dict[str, object]", document)
    snapshot = SubscriptionDocument(
        schema_version=fields.get("schema_version"),
        timezone=fields.get("timezone"),
        accounts=fields.get("accounts"),
    )
    return subscription_expiry(snapshot, label=label, now=now)


def subscription_expiry(
    document: SubscriptionDocument, *, label: str, now: datetime,
) -> dict[str, str | None]:
    """Select confirmed end-date evidence, preserving its calendar precision.

    Returns:
        Unknown for missing, stale, renewing, or unverified subscription evidence.

    Raises:
        PayloadError: Snapshot schema or account identity is ambiguous.
    """
    rows = document.get("accounts")
    if document.get("schema_version") != 1 or not isinstance(rows, list):
        message = "subscription snapshot schema is invalid"
        raise PayloadError(message)
    matches: list[dict[str, object]] = []
    for raw in cast("list[object]", rows):
        if not isinstance(raw, dict):
            message = "subscription account must be an object"
            raise PayloadError(message)
        row = cast("dict[str, object]", raw)
        email = row.get("email")
        if isinstance(email, str) and email.strip().casefold() == label.casefold():
            matches.append(row)
    if len(matches) > 1:
        message = "subscription snapshot has duplicate account identities"
        raise PayloadError(message)
    unknown: dict[str, str | None] = {"subscription_access_ends_on": None}
    if not matches:
        return unknown
    row = matches[0]
    if row.get("access_status") != "active" or row.get("renewal_enabled") is not False:
        return unknown
    end = row.get("access_ends_on")
    source = row.get("verified_source")
    if not all(isinstance(value, str) and value.strip() for value in (end, row.get("verified_at"), source)):
        return unknown
    verified_at = parse_timestamp(row.get("verified_at"), field_name="subscription.verified_at")
    if not timedelta(0) <= now - verified_at <= MAX_VERIFIED_AGE:
        return unknown
    zone = document.get("timezone")
    if not isinstance(zone, str):
        message = "confirmed subscription end date requires a timezone"
        raise PayloadError(message)
    result = {
        "subscription_access_ends_on": date.fromisoformat(cast("str", end)).isoformat(),
        "subscription_timezone": ZoneInfo(zone).key,
        "subscription_verified_at": utc_iso(verified_at),
        "subscription_source": "reviewed_subscription_snapshot",
    }
    return {**result, **_precise_cutoff(
        SubscriptionCutoff(access_ends_at=row.get("access_ends_at")),
        end=result["subscription_access_ends_on"], zone=zone,
    )}


def _precise_cutoff(row: SubscriptionCutoff, *, end: str, zone: str) -> dict[str, str]:
    exact = row.get("access_ends_at")
    if exact is not None:
        cutoff = parse_timestamp(exact, field_name="subscription.access_ends_at")
        if cutoff.astimezone(ZoneInfo(zone)).date().isoformat() != end:
            message = "subscription exact cutoff disagrees with its calendar date"
            raise PayloadError(message)
        return {"subscription_access_ends_at": utc_iso(cutoff)}
    return {}


def confirmed_end_date(observation: AccountObservation) -> str | None:
    """Return the separately verified subscription date, never a credit expiry."""
    value = cast("object", observation.broker_state.get("subscription_access_ends_on"))
    return value if isinstance(value, str) else None


def subscription_may_have_ended(observation: AccountObservation, *, now: datetime) -> bool:
    """Avoid redemption on or after a date-only access end, without reactivation.

    Returns:
        True when the confirmed access-end day has begun in its source timezone.
    """
    exact = confirmed_end_time(observation)
    if exact is not None:
        return exact <= now
    end = confirmed_end_date(observation)
    if end is None:
        return False
    zone = cast("str", observation.broker_state["subscription_timezone"])
    return date.fromisoformat(end) <= now.astimezone(ZoneInfo(zone)).date()


def confirmed_end_time(observation: AccountObservation) -> datetime | None:
    """Return the verified entitlement cutoff, never the cancellation request time."""
    value = cast("object", observation.broker_state.get("subscription_access_ends_at"))
    return parse_timestamp(value, field_name="subscription.access_ends_at") if value is not None else None


def subscription_end_upper_bound(observation: AccountObservation) -> datetime | None:
    """Bound a date-only end for natural-reset comparisons.

    Returns:
        The precise entitlement cutoff or the upper bound of its entire end day.
    """
    exact = confirmed_end_time(observation)
    if exact is not None:
        return exact
    end = confirmed_end_date(observation)
    if end is None:
        return None
    zone = cast("str", observation.broker_state["subscription_timezone"])
    return datetime.combine(date.fromisoformat(end) + timedelta(days=1), time.min, ZoneInfo(zone))
