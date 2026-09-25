# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build upcoming capacity-reset events for the dashboard timeline."""

from __future__ import annotations

from datetime import timedelta
from operator import itemgetter
from typing import TYPE_CHECKING

from .value_parsing import isoformat, parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityAccount, CapacityEvent, CapacityWindow

CAPACITY_EVENT_HORIZON_SECONDS = 8 * 24 * 60 * 60


def capacity_events(
    accounts: list[CapacityAccount],
    *,
    now: datetime,
    horizon_seconds: int = CAPACITY_EVENT_HORIZON_SECONDS,
) -> list[CapacityEvent]:
    """Return reported resets within the configured event horizon."""
    horizon_end = now + timedelta(seconds=horizon_seconds)
    events: list[CapacityEvent] = []
    for account in accounts:
        if not account["enabled"] or account["auth_valid"] is not True:
            continue
        windows = (
            ("five_hour_reset", account["five_hour"]),
            ("weekly_reset", account["weekly"]),
        )
        for kind, window in windows:
            event = _capacity_event(
                account,
                kind=kind,
                window=window,
                now=now,
                horizon_end=horizon_end,
            )
            if event is not None:
                events.append(event)
    events.sort(key=itemgetter("at", "account_label", "kind"))
    return events


def _capacity_event(
    account: CapacityAccount,
    *,
    kind: str,
    window: CapacityWindow,
    now: datetime,
    horizon_end: datetime,
) -> CapacityEvent | None:
    if window.get("reported") is not True:
        return None
    reset_at = parse_datetime(window.get("reset_at"))
    if reset_at is None or not now < reset_at <= horizon_end:
        return None
    return {
        "kind": kind,
        "account_label": account["label"],
        "at": isoformat(reset_at),
        "in_seconds": int((reset_at - now).total_seconds()),
        "capacity_points": 100,
        "restores_selectability": _restores_selectability(
            account,
            kind=kind,
        ),
    }


def _restores_selectability(account: CapacityAccount, *, kind: str) -> bool:
    five_hour_restore = kind == "five_hour_reset" and account["status"] == "five_hour_limited"
    weekly_restore = kind == "weekly_reset" and account["status"] == "weekly_limited"
    return five_hour_restore or weekly_restore
