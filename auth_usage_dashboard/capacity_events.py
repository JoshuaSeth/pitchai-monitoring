# Copyright (c) 2026 PitchAI. All rights reserved.
"""Upcoming automatic window resets and the read-only banked reset inventory."""

from __future__ import annotations

from datetime import timedelta
from operator import itemgetter
from typing import TYPE_CHECKING

from .capacity_values import isoformat, parse_timestamp
from .timeseries_types import optional_object

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject, JsonValue

type _EventEntry = tuple[tuple[str, str, str], JsonObject]
type _BankEntry = tuple[tuple[bool, str, str], JsonObject, datetime | None]

_RESET_KINDS = (
    ("five_hour_reset", "five_hour", "five_hour_limited"),
    ("weekly_reset", "weekly", "weekly_limited"),
)
_RESET_EVENT_POINTS = 100


def capacity_events(accounts: list[JsonObject], *, now: datetime, horizon_seconds: int) -> list[JsonObject]:
    """List the reported window resets of auth-valid accounts within the horizon.

    Returns:
        Reset events ordered by time, account label, and reset kind.
    """
    horizon_end = now + timedelta(seconds=horizon_seconds)
    entries: list[_EventEntry] = []
    for account in accounts:
        if not account["enabled"] or account["auth_valid"] is not True:
            continue
        label = str(account["label"])
        for kind, window_key, restored_status in _RESET_KINDS:
            window = optional_object(account[window_key])
            reset_at = parse_timestamp(window.get("reset_at")) if window.get("reported") is True else None
            if reset_at is None or not now < reset_at <= horizon_end:
                continue
            at = isoformat(reset_at)
            event: JsonObject = {
                "kind": kind,
                "account_label": label,
                "at": at,
                "in_seconds": int((reset_at - now).total_seconds()),
                "capacity_points": _RESET_EVENT_POINTS,
                "restores_selectability": account["status"] == restored_status,
            }
            entries.append(((at or "", label, kind), event))
    entries.sort(key=itemgetter(0))
    return [event for _order, event in entries]


def reset_bank(accounts: list[JsonObject], *, now: datetime) -> JsonObject:
    """Inventory banked resets across accounts without offering any way to redeem them.

    Returns:
        Known reset counts, expiry-ordered reset details, and the earliest future expiry.
    """
    entries: list[_BankEntry] = []
    known_counts: list[int] = []
    count_only_accounts = 0
    for account in accounts:
        inventory = optional_object(account["reset_credits"])
        count = inventory.get("available_count")
        account_details = inventory.get("details")
        if isinstance(count, int):
            known_counts.append(count)
        if not isinstance(account_details, list):
            continue
        if isinstance(count, int) and count > len(account_details):
            count_only_accounts += 1
        entries.extend(_bank_entries(account_details, label=str(account["label"]), now=now))
    entries.sort(key=itemgetter(0))
    details: list[JsonValue] = [detail for _order, detail, _expiry in entries]
    future_expiries: list[datetime] = []
    for _order, _detail, expiry in entries:
        if expiry is not None and expiry > now:
            future_expiries.append(expiry)
    return {
        "total_available": sum(known_counts),
        "accounts_with_known_count": len(known_counts),
        "accounts_with_unknown_count": len(accounts) - len(known_counts),
        "count_only_accounts": count_only_accounts,
        "detail_count": len(details),
        "details": details,
        "earliest_expiry_at": isoformat(min(future_expiries, default=None)),
        "stale_account_count": sum(1 for account in accounts if optional_object(account["reset_credits"])["stale"]),
    }


def _bank_entries(account_details: list[JsonValue], *, label: str, now: datetime) -> list[_BankEntry]:
    entries: list[_BankEntry] = []
    for raw_detail in account_details:
        detail = optional_object(raw_detail)
        expires = detail.get("expires_at")
        expires_at = parse_timestamp(expires)
        bank_detail: JsonObject = {
            "account_label": label,
            "reset_type": detail.get("reset_type"),
            "status": detail.get("status"),
            "title": detail.get("title"),
            "granted_at": detail.get("granted_at"),
            "expires_at": expires,
            "expires_in_seconds": None if expires_at is None else int((expires_at - now).total_seconds()),
        }
        order = (expires is None, expires if isinstance(expires, str) else "", label.lower())
        entries.append((order, bank_detail, expires_at))
    return entries
