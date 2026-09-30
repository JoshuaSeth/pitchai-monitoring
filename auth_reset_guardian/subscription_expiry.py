# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read reviewed subscription end dates without inferring billing from quota."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from .models import PayloadError, parse_timestamp, utc_iso

if TYPE_CHECKING:
    from datetime import datetime

    from .models import AccountObservation

SUBSCRIPTION_FILE = Path("/srv/codex-usage-dashboard/codex-subscriptions.json")
MAX_VERIFIED_AGE = timedelta(days=30)
MAX_SNAPSHOT_BYTES = 131_072


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
    return subscription_expiry(
        cast("dict[str, object]", document), label=label, now=now,
    )


def subscription_expiry(
    document: dict[str, object], *, label: str, now: datetime,
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
    verified = row.get("verified_at")
    source = row.get("verified_source")
    if not all(isinstance(value, str) and value.strip() for value in (end, verified, source)):
        return unknown
    verified_at = parse_timestamp(verified, field_name="subscription.verified_at")
    if not timedelta(0) <= now - verified_at <= MAX_VERIFIED_AGE:
        return unknown
    zone = document.get("timezone")
    if not isinstance(zone, str):
        message = "confirmed subscription end date requires a timezone"
        raise PayloadError(message)
    return {
        "subscription_access_ends_on": date.fromisoformat(cast("str", end)).isoformat(),
        "subscription_timezone": ZoneInfo(zone).key,
        "subscription_verified_at": utc_iso(verified_at),
        "subscription_source": "reviewed_subscription_snapshot",
    }


def confirmed_end_date(observation: AccountObservation) -> str | None:
    """Return the separately verified subscription date, never a credit expiry."""
    value = cast("object", observation.broker_state.get("subscription_access_ends_on"))
    return value if isinstance(value, str) else None


def subscription_may_have_ended(observation: AccountObservation, *, now: datetime) -> bool:
    """Avoid redemption on or after a date-only access end, without reactivation.

    Returns:
        True when the confirmed access-end day has begun in its source timezone.
    """
    end = confirmed_end_date(observation)
    if end is None:
        return False
    zone = cast("str", observation.broker_state["subscription_timezone"])
    return date.fromisoformat(end) <= now.astimezone(ZoneInfo(zone)).date()
