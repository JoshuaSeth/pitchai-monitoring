# Copyright (c) 2026 PitchAI. All rights reserved.
"""Transient host-aware records for the deployed nginx monitoring format."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue

_COMBINED = re.compile(
    r'^\S+\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+"[^\"]*"\s+'
    r'(?P<status>\d{3})\s+\S+\s+"[^\"]*"\s+"(?P<agent>[^\"]*)"'
    r'(?:\s+"(?P<host>[^\"]*)")?\s*$',
)


@dataclass(frozen=True)
class AccessRecord:
    """Request attributes exist only while calculating the current window."""

    timestamp: float
    status: int
    host: str | None
    agent: str


def parse_access_record(line: str) -> AccessRecord | None:
    """Accept deployed JSON and historical combined records.

    Returns:
        A transient request record, or None for an invalid complete line.
    """
    if line.lstrip().startswith("{"):
        return _json_record(line)
    match = _COMBINED.fullmatch(line.strip())
    if match is None:
        return None
    observed: datetime | None = None
    with suppress(ValueError):
        observed = datetime.strptime(match["ts"], "%d/%b/%Y:%H:%M:%S %z")
    if observed is None:
        return None
    host = (match["host"] or "").strip().lower().rstrip(".") or None
    return AccessRecord(observed.timestamp(), int(match["status"]), host, match["agent"])


def _json_record(line: str) -> AccessRecord | None:
    payload: JsonValue = None
    with suppress(ValueError, RecursionError):
        payload = cast("JsonValue", json.loads(line))
    if not isinstance(payload, dict):
        return None
    timestamp, status, host, agent = (
        payload.get("timestamp"), payload.get("status"), payload.get("host"), payload.get("user_agent"),
    )
    if (not isinstance(timestamp, str) or not isinstance(status, int) or isinstance(status, bool)
            or not isinstance(host, str) or not isinstance(agent, str)):
        return None
    observed: datetime | None = None
    with suppress(ValueError):
        observed = datetime.fromisoformat(timestamp)
    if observed is None or observed.tzinfo is None or not host.strip():
        return None
    return AccessRecord(observed.timestamp(), status, host.strip().lower().rstrip("."), agent)
