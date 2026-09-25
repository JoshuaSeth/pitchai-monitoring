# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read and decode persisted guardian events for behavior tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.json_contract import decode_json
from tests.auth_reset_guardian_support import required_text
from tests.auth_test_contract import FixtureContractError

if TYPE_CHECKING:
    from pathlib import Path

    from auth_reset_guardian.json_contract import JsonObject


def read_events(db_path: Path) -> list[JsonObject]:
    """Read guardian events in chronological order.

    Returns:
        The resulting collection.

    """
    with AuditStore(db_path) as audit:
        events = audit.recent_events(limit=10_000)
    events.reverse()
    return events


def event_details(event: JsonObject) -> JsonObject:
    """Decode one persisted guardian event's bounded details object.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If persisted event details are not an object.

    """
    details = decode_json(required_text(event, "details_json"))
    if not isinstance(details, dict):
        msg = "guardian event details must contain an object"
        raise FixtureContractError(msg)
    return details
