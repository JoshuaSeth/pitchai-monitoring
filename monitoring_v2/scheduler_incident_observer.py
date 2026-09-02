# Copyright (c) 2026 PitchAI. All rights reserved.
"""Observe central scheduler failures from storage independent of execution cells."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from .event_bus_delivery import DatabaseEventBus
from .json_types import optional_object
from .scheduler_incident_feed import (
    load_scheduler_incident_feed_config,
    read_scheduler_incident_page,
    scheduler_cursor_from_value,
    scheduler_cursor_value,
)
from .scheduler_incident_state import (
    SchedulerStateUpdate,
    initial_scheduler_state,
    load_scheduler_state,
    record_scheduler_cycle_error,
    updated_scheduler_state,
)
from .state_io import write_state

if TYPE_CHECKING:
    from httpx import BaseTransport

    from .event_bus_runtime import DeliveryAttempt
    from .json_types import JsonObject

LOGGER = logging.getLogger(__name__)

_DEFAULT_STATE_PATH = "/data/scheduler-placement-observer.json"
_DEFAULT_POLL_SECONDS = 15.0
_MAX_POLL_SECONDS = 300.0


class SchedulerObserverReceipt(NamedTuple):
    """Inspectable bounded-cycle outcome."""

    status: str
    observed_count: int
    delivered_count: int
    pending_count: int


class _CycleContext(NamedTuple):
    """Immutable inputs shared by one bounded observer cycle."""

    state_path: Path
    now: float
    transport: BaseTransport | None


class _PreflightResult(NamedTuple):
    """Events Bus state after retained deliveries receive one bounded attempt."""

    event_bus: DatabaseEventBus
    attempts: tuple[DeliveryAttempt, ...]
    delivered_count: int
    receipt: SchedulerObserverReceipt | None


def run_cycle(
    *,
    state_path: Path,
    now: float | None = None,
    transport: BaseTransport | None = None,
) -> SchedulerObserverReceipt:
    """Checkpoint one feed page and drain its durable Events Bus outbox.

    Returns:
        One compact cycle receipt without incident contents or credentials.
    """
    selected_now = time.time() if now is None else now
    context = _CycleContext(state_path=state_path, now=selected_now, transport=transport)
    retained = load_scheduler_state(state_path)
    if not retained:
        initialized = initial_scheduler_state(selected_now)
        write_state(state_path, initialized)
        return SchedulerObserverReceipt("bootstrapped", 0, 0, 0)

    preflight = _preflight_delivery(retained, context)
    if preflight.receipt is not None:
        return preflight.receipt
    return _poll_and_deliver(retained, context, preflight)


def _preflight_delivery(retained: JsonObject, context: _CycleContext) -> _PreflightResult:
    """Attempt retained outbox entries before advancing the central cursor.

    Returns:
        The configured bus, attempts, count, and optional backoff receipt.

    Raises:
        RuntimeError: If signed Events Bus delivery is not configured.
    """
    event_bus = DatabaseEventBus.from_state(retained)
    if event_bus is None:
        message = "scheduler observer Events Bus delivery is not configured"
        raise RuntimeError(message)
    preflight_attempts = event_bus.flush(now=context.now, transport=context.transport)
    preflight_delivered = sum(attempt.success for attempt in preflight_attempts)
    if event_bus.pending_count:
        waiting = updated_scheduler_state(
            retained,
            SchedulerStateUpdate(
                outbox=event_bus.state_value(),
                now=context.now,
                attempts=preflight_attempts,
            ),
        )
        write_state(context.state_path, waiting)
        receipt = SchedulerObserverReceipt("delivery_backoff", 0, preflight_delivered, event_bus.pending_count)
        return _PreflightResult(event_bus, preflight_attempts, preflight_delivered, receipt)
    return _PreflightResult(event_bus, preflight_attempts, preflight_delivered, None)


def _poll_and_deliver(
    retained: JsonObject,
    context: _CycleContext,
    preflight: _PreflightResult,
) -> SchedulerObserverReceipt:
    """Checkpoint one central page before attempting its receiver deliveries.

    Returns:
        The observed, delivered, and still-pending counts for the page.
    """
    config = load_scheduler_incident_feed_config()
    cursor = scheduler_cursor_from_value(optional_object(retained.get("cursor")))
    page = read_scheduler_incident_page(config, cursor)
    staged_bus = preflight.event_bus.staged_events(page.events)
    checkpoint = updated_scheduler_state(
        retained,
        SchedulerStateUpdate(
            outbox=staged_bus.state_value(),
            now=context.now,
            cursor=scheduler_cursor_value(page.next_cursor),
            attempts=preflight.attempts,
            clear_error=True,
            poll_succeeded=True,
        ),
    )
    write_state(context.state_path, checkpoint)

    delivery_attempts = staged_bus.flush(now=context.now, transport=context.transport)
    delivered = preflight.delivered_count + sum(attempt.success for attempt in delivery_attempts)
    final_state = updated_scheduler_state(
        checkpoint,
        SchedulerStateUpdate(
            outbox=staged_bus.state_value(),
            now=context.now,
            attempts=delivery_attempts,
        ),
    )
    write_state(context.state_path, final_state)
    return SchedulerObserverReceipt("ready", len(page.events), delivered, staged_bus.pending_count)


def _poll_seconds() -> float:
    selected = float(os.getenv("SCHEDULER_INCIDENT_POLL_SECONDS", str(_DEFAULT_POLL_SECONDS)))
    if not 1.0 <= selected <= _MAX_POLL_SECONDS:
        message = "SCHEDULER_INCIDENT_POLL_SECONDS must be between 1 and 300"
        raise ValueError(message)
    return selected


def _run_and_log_cycle(state_path: Path) -> None:
    receipt = run_cycle(state_path=state_path)
    if receipt.observed_count or receipt.delivered_count or receipt.pending_count:
        LOGGER.info("scheduler incident observer receipt=%s", receipt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    configured_state_path = Path(os.getenv("SCHEDULER_INCIDENT_STATE_PATH", _DEFAULT_STATE_PATH))
    configured_poll_seconds = _poll_seconds()
    while True:
        cycle_started = time.monotonic()
        try:
            _run_and_log_cycle(configured_state_path)
        except (OSError, RuntimeError, TypeError, ValueError) as cycle_error:
            LOGGER.exception("scheduler incident observer cycle failed error_type=%s", type(cycle_error).__name__)
            if configured_state_path.exists():
                record_scheduler_cycle_error(configured_state_path, cycle_error, now=time.time())
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(1.0, configured_poll_seconds - elapsed))
