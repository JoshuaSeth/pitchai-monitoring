# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove scheduler failures survive cell-local capacity loss and reach the receiver boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import scheduler_incident_observer as observer_module
from .domain_event_test_support import accepted_requests, configure_event_bus
from .event_bus_runtime import DELIVERY_RUNTIME, DeliveryAttempt
from .json_types import object_list, optional_object, text_value
from .scheduler_incident_feed import (
    load_scheduler_incident_feed_config,
    scheduler_incident_page,
)
from .scheduler_incident_observer import run_cycle
from .scheduler_incident_test_support import EVENT_ID, TOKEN, incident_feed
from .state_io import load_state
from .testing_runtime import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import BaseTransport

    from .event_bus_runtime import DeliveryPayload, EventBusConfig
    from .json_types import JsonObject
    from .scheduler_incident_feed import SchedulerIncidentCursor, SchedulerIncidentFeedConfig, SchedulerIncidentPage
    from .testing_runtime import MonkeyPatch

_START_TIME = 1_788_278_400.0
_EVENT_TIME = _START_TIME + 0.5


def _configure(monkeypatch: MonkeyPatch) -> None:
    configure_event_bus(monkeypatch)
    monkeypatch.setenv("PITCHAI_PLATFORM_CENTRAL_URL", "https://platform.pitchai.net")
    monkeypatch.setenv("PITCHAI_PLATFORM_USER_TOKEN", TOKEN)


def test_feed_config_requires_https_origin_and_bounded_token() -> None:
    """Reject ambiguous endpoints and accept the exact central API origin."""
    config = load_scheduler_incident_feed_config(
        {
            "PITCHAI_PLATFORM_CENTRAL_URL": "https://platform.pitchai.net/",
            "PITCHAI_PLATFORM_USER_TOKEN": TOKEN,
        },
    )
    if config.url != "https://platform.pitchai.net/internal/global-api/v2/scheduler/new-lane-failures":
        pytest.fail(f"unexpected scheduler feed URL: {config.url}")

    with pytest.raises(RuntimeError):
        _ = load_scheduler_incident_feed_config(
            {
                "PITCHAI_PLATFORM_CENTRAL_URL": "http://platform.pitchai.net",
                "PITCHAI_PLATFORM_USER_TOKEN": TOKEN,
            },
        )


def test_observer_checkpoints_then_delivers_through_events_bus(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Persist the central cursor and signed outbox outside the failing cell."""
    _configure(monkeypatch)
    state_path = tmp_path / "scheduler-observer.json"
    captured: list[JsonObject] = []

    def read_page(
        config: SchedulerIncidentFeedConfig,
        cursor: SchedulerIncidentCursor,
    ) -> SchedulerIncidentPage:
        if config.token != TOKEN:
            pytest.fail("observer did not use its configured central user token")
        return scheduler_incident_page(incident_feed(), prior_cursor=cursor)

    monkeypatch.setattr(observer_module, "read_scheduler_incident_page", read_page)
    transport = accepted_requests(captured)
    bootstrapped = run_cycle(state_path=state_path, now=_START_TIME, transport=transport)
    delivered = run_cycle(state_path=state_path, now=_START_TIME + 1.0, transport=transport)

    if bootstrapped.status != "bootstrapped" or delivered.delivered_count != 1:
        pytest.fail(f"scheduler observer did not bootstrap and deliver: {bootstrapped}, {delivered}")
    state = load_state(state_path)
    if object_list(state.get("event_bus_outbox")):
        pytest.fail("accepted scheduler event remained in the durable outbox")
    cursor = optional_object(state.get("cursor"))
    if cursor.get("event_id") != EVENT_ID:
        pytest.fail(f"central cursor was not checkpointed: {cursor}")
    if TOKEN in state_path.read_text(encoding="utf-8"):
        pytest.fail("scheduler observer persisted its bearer token")

    payload = captured[-1]
    if payload.get("event_kind") != "production_failure":
        pytest.fail(f"unexpected receiver event: {payload}")
    if "Telegram" in state_path.read_text(encoding="utf-8"):
        pytest.fail("scheduler observer state contains a direct notification route")


def test_failed_receiver_delivery_remains_durable_without_refetch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Retain one failed signed delivery and avoid unbounded feed growth during backoff."""
    _configure(monkeypatch)
    state_path = tmp_path / "scheduler-observer.json"
    feed_reads: list[int] = []
    attempted_delivery_ids: list[str] = []

    def read_page(
        config: SchedulerIncidentFeedConfig,
        cursor: SchedulerIncidentCursor,
    ) -> SchedulerIncidentPage:
        if config.token != TOKEN:
            pytest.fail("observer did not use its configured central user token")
        feed_reads.append(cursor.event_id)
        return scheduler_incident_page(incident_feed(), prior_cursor=cursor)

    def reject_delivery(
        config: EventBusConfig,
        immutable_payload: DeliveryPayload,
        *,
        now: float | None = None,
        transport: BaseTransport | None = None,
    ) -> DeliveryAttempt:
        del config, now, transport
        delivery_id = text_value(immutable_payload.get("delivery_id"))
        attempted_delivery_ids.append(delivery_id)
        return DeliveryAttempt(
            error="http_status_503",
            event_id=None,
            status_code=503,
            success=False,
            delivery_id=delivery_id,
        )

    monkeypatch.setattr(observer_module, "read_scheduler_incident_page", read_page)
    monkeypatch.setattr(DELIVERY_RUNTIME, "deliver_event_bus_payload", reject_delivery)
    _ = run_cycle(state_path=state_path, now=_START_TIME)
    failed = run_cycle(state_path=state_path, now=_START_TIME + 1.0)
    waiting = run_cycle(state_path=state_path, now=_START_TIME + 2.0)

    state = load_state(state_path)
    if failed.pending_count != 1 or waiting.status != "delivery_backoff":
        pytest.fail(f"failed delivery was not retained: {failed}, {waiting}")
    if len(object_list(state.get("event_bus_outbox"))) != 1 or len(feed_reads) != 1 or len(attempted_delivery_ids) != 1:
        pytest.fail("observer refetched incidents while a durable delivery was still pending")
