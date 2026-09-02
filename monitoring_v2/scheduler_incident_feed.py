# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict reader and event adapter for durable scheduler placement failures."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import urlparse

from .json_types import object_list
from .scheduler_incident_event import placement_failure_event, required_timestamp
from .scheduler_incident_gateway import read_scheduler_json

if TYPE_CHECKING:
    from .domain_event_models import DomainTransitionEvent
    from .json_types import JsonObject

_FEED_PATH = "/internal/global-api/v2/scheduler/new-lane-failures"
_DIRECTORY_PATH = "/internal/global-api/v2/directory"
_ZERO_EVENT_ID = 0
_MAX_TIMEOUT_SECONDS = 60.0
_MIN_TOKEN_LENGTH = 32
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class SchedulerIncidentFeedConfig(NamedTuple):
    """Authenticated read-only scheduler incident feed configuration."""

    url: str
    directory_url: str
    token: str
    timeout_seconds: float


class SchedulerIncidentCursor(NamedTuple):
    """Stable timestamp-plus-id cursor for the central audit stream."""

    occurred_at: str
    event_id: int


class SchedulerIncidentPage(NamedTuple):
    """One validated bounded page and its next durable cursor."""

    events: tuple[DomainTransitionEvent, ...]
    next_cursor: SchedulerIncidentCursor


def load_scheduler_incident_feed_config(
    environ: dict[str, str] | None = None,
) -> SchedulerIncidentFeedConfig:
    """Load the central URL and user token without persisting either value.

    Returns:
        Validated feed settings for the observer.

    Raises:
        RuntimeError: If the central origin, token, or timeout is unsafe.
    """
    source = os.environ if environ is None else environ
    central_url = str(source.get("PITCHAI_PLATFORM_CENTRAL_URL") or "").strip().rstrip("/")
    token = str(source.get("PITCHAI_PLATFORM_USER_TOKEN") or "").strip()
    parsed = urlparse(central_url)
    loopback_http = parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS
    if (parsed.scheme != "https" and not loopback_http) or not parsed.netloc or parsed.username or parsed.password:
        message = "PITCHAI_PLATFORM_CENTRAL_URL must be HTTPS or exact loopback HTTP without userinfo"
        raise RuntimeError(message)
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        message = "PITCHAI_PLATFORM_CENTRAL_URL must not contain a path, query, or fragment"
        raise RuntimeError(message)
    if len(token) < _MIN_TOKEN_LENGTH:
        message = "PITCHAI_PLATFORM_USER_TOKEN must contain at least 32 characters"
        raise RuntimeError(message)
    timeout = float(source.get("SCHEDULER_INCIDENT_FEED_TIMEOUT_SECONDS") or "10")
    if not 1.0 <= timeout <= _MAX_TIMEOUT_SECONDS:
        message = "SCHEDULER_INCIDENT_FEED_TIMEOUT_SECONDS must be between 1 and 60"
        raise RuntimeError(message)
    return SchedulerIncidentFeedConfig(
        url=f"{central_url}{_FEED_PATH}",
        directory_url=f"{central_url}{_DIRECTORY_PATH}",
        token=token,
        timeout_seconds=timeout,
    )


def initial_scheduler_cursor(now: float) -> SchedulerIncidentCursor:
    """Start at deployment time so rollout does not replay historical incidents.

    Returns:
        A stable initial timestamp-plus-id cursor.
    """
    occurred_at = datetime.fromtimestamp(now, tz=UTC).isoformat(timespec="microseconds")
    normalized_occurred_at = occurred_at.replace("+00:00", "Z")
    return SchedulerIncidentCursor(occurred_at=normalized_occurred_at, event_id=_ZERO_EVENT_ID)


def read_scheduler_incident_page(
    config: SchedulerIncidentFeedConfig,
    cursor: SchedulerIncidentCursor,
) -> SchedulerIncidentPage:
    """Read and validate one central incident page.

    Returns:
        Events Bus transitions plus the exact server cursor.
    """
    payload = read_scheduler_json(
        url=config.url,
        token=config.token,
        timeout_seconds=config.timeout_seconds,
        query={
            "after_occurred_at": cursor.occurred_at,
            "after_event_id": str(cursor.event_id),
            "limit": "100",
        },
    )
    return scheduler_incident_page(payload, prior_cursor=cursor)


def scheduler_incident_page(
    payload: JsonObject,
    *,
    prior_cursor: SchedulerIncidentCursor,
) -> SchedulerIncidentPage:
    """Convert a strict central feed document into actionable transitions.

    Returns:
        Validated transitions and a non-regressing cursor.

    Raises:
        TypeError: If the response does not follow the bounded feed schema.
        ValueError: If a signal or cursor value is invalid or regresses.
    """
    raw_incidents = payload.get("incidents")
    incidents = object_list(raw_incidents)
    if not isinstance(raw_incidents, list) or len(incidents) != len(raw_incidents):
        message = "scheduler incident feed incidents must be an object array"
        raise TypeError(message)
    events = tuple(placement_failure_event(incident) for incident in incidents)
    next_occurred_at = required_timestamp(payload, "next_occurred_at")
    next_event_id = _required_event_id(payload, "next_event_id")
    next_cursor = SchedulerIncidentCursor(next_occurred_at, next_event_id)
    if _cursor_order(next_cursor) < _cursor_order(prior_cursor):
        message = "scheduler incident feed cursor regressed"
        raise ValueError(message)
    return SchedulerIncidentPage(events=events, next_cursor=next_cursor)


def scheduler_cursor_value(cursor: SchedulerIncidentCursor) -> JsonObject:
    """Return a compact persisted cursor object."""
    persisted: JsonObject = {"occurred_at": cursor.occurred_at, "event_id": cursor.event_id}
    return persisted


def scheduler_cursor_from_value(value: JsonObject) -> SchedulerIncidentCursor:
    """Validate and restore a persisted cursor.

    Returns:
        A strict timestamp-plus-id cursor.
    """
    return SchedulerIncidentCursor(
        occurred_at=required_timestamp(value, "occurred_at"),
        event_id=_required_event_id(value, "event_id"),
    )


def _required_event_id(payload: JsonObject, field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        message = f"scheduler incident field {field} must be a non-negative integer"
        raise TypeError(message)
    return value


def _cursor_order(cursor: SchedulerIncidentCursor) -> tuple[datetime, int]:
    timestamp = datetime.fromisoformat(cursor.occurred_at)
    return timestamp, cursor.event_id
