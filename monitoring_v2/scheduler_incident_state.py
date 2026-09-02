# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict durable state for the scheduler placement incident observer."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

from .json_types import json_object, normalize_json, object_list, optional_object
from .scheduler_incident_feed import (
    initial_scheduler_cursor,
    scheduler_cursor_from_value,
    scheduler_cursor_value,
)
from .state_io import load_state, write_state

if TYPE_CHECKING:
    from pathlib import Path

    from .event_bus_runtime import DeliveryAttempt
    from .json_types import JsonInput, JsonObject, JsonValue

_STATE_VERSION = 1


class SchedulerStateUpdate(NamedTuple):
    """Typed state fields changed after one feed or delivery operation."""

    outbox: JsonValue
    now: float
    attempts: tuple[DeliveryAttempt, ...]
    cursor: JsonObject | None = None
    clear_error: bool = False
    poll_succeeded: bool = False
    cells: JsonObject | None = None
    directory_polled: bool = False


def initial_scheduler_state(now: float) -> JsonObject:
    """Return a deployment-time cursor with an empty receiver outbox."""
    return json_object(
        {
            "version": _STATE_VERSION,
            "bootstrapped": True,
            "cursor": scheduler_cursor_value(initial_scheduler_cursor(now)),
            "cells": {},
            "event_bus_outbox": [],
            "updated_at_ts": now,
            "last_error": None,
            "last_delivery_id": None,
            "last_receiver_event_id": None,
            "last_delivered_at_ts": None,
            "last_successful_poll_at_ts": None,
            "last_successful_directory_poll_at_ts": None,
        },
    )


def load_scheduler_state(path: Path) -> JsonObject:
    """Load and validate one observer checkpoint.

    Returns:
        An empty object before bootstrap, or one strict checkpoint.

    Raises:
        TypeError: If retained state has an unsupported or unsafe shape.
    """
    state = load_state(path)
    if not state:
        return {}
    if state.get("version") != _STATE_VERSION or state.get("bootstrapped") is not True:
        message = "scheduler observer state version or bootstrap marker is invalid"
        raise TypeError(message)
    _ = scheduler_cursor_from_value(optional_object(state.get("cursor")))
    raw_cells = state.get("cells", {})
    if not isinstance(raw_cells, dict):
        message = "scheduler observer cells must be an object"
        raise TypeError(message)
    state["cells"] = optional_object(raw_cells)
    state.setdefault("last_successful_directory_poll_at_ts", None)
    raw_outbox = state.get("event_bus_outbox")
    if not isinstance(raw_outbox, list) or len(object_list(raw_outbox)) != len(raw_outbox):
        message = "scheduler observer outbox must contain only objects"
        raise TypeError(message)
    return state


def updated_scheduler_state(retained: JsonObject, update: SchedulerStateUpdate) -> JsonObject:
    """Apply delivery receipts and one optional feed checkpoint.

    Returns:
        A complete normalized state document ready for atomic persistence.
    """
    last_delivery_id = retained.get("last_delivery_id")
    last_receiver_event_id = retained.get("last_receiver_event_id")
    last_delivered_at = retained.get("last_delivered_at_ts")
    last_error = None if update.clear_error else retained.get("last_error")
    for attempt in update.attempts:
        if attempt.success:
            last_delivery_id = attempt.delivery_id
            last_receiver_event_id = attempt.event_id
            last_delivered_at = update.now
            last_error = None
        else:
            last_error = f"event_bus_delivery:{attempt.error or 'unknown'}"
    raw = {
        "version": _STATE_VERSION,
        "bootstrapped": True,
        "cursor": update.cursor if update.cursor is not None else optional_object(retained.get("cursor")),
        "cells": update.cells if update.cells is not None else optional_object(retained.get("cells")),
        "event_bus_outbox": normalize_json(cast("JsonInput", update.outbox)),
        "updated_at_ts": update.now,
        "last_error": last_error,
        "last_delivery_id": last_delivery_id,
        "last_receiver_event_id": last_receiver_event_id,
        "last_delivered_at_ts": last_delivered_at,
        "last_successful_poll_at_ts": (
            update.now if update.poll_succeeded else retained.get("last_successful_poll_at_ts")
        ),
        "last_successful_directory_poll_at_ts": (
            update.now
            if update.directory_polled
            else retained.get("last_successful_directory_poll_at_ts")
        ),
    }
    return json_object(cast("JsonInput", raw))


def record_scheduler_cycle_error(path: Path, error: BaseException, *, now: float) -> None:
    """Retain a non-secret failure class without discarding the durable outbox."""
    retained = load_scheduler_state(path)
    retained["updated_at_ts"] = now
    retained["last_error"] = f"cycle_failure:{type(error).__name__}"
    write_state(path, retained)
