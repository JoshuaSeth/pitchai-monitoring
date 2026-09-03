# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove scheduler failures survive cell-local capacity loss and reach the receiver boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import scheduler_incident_observer as observer_module
from .domain_event_test_support import accepted_requests, configure_event_bus
from .event_bus_runtime import DELIVERY_RUNTIME, DeliveryAttempt
from .json_types import float_value, object_list, optional_object, text_value
from .scheduler_cell_test_support import cell_observation
from .scheduler_incident_feed import (
    SchedulerIncidentPage,
    load_scheduler_incident_feed_config,
    scheduler_incident_page,
)
from .scheduler_incident_observer import run_cycle
from .scheduler_incident_test_support import EVENT_ID, RECOVERY_EVENT_ID, TOKEN, incident_feed, recovery_feed
from .state_io import load_state
from .testing_runtime import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import BaseTransport

    from .event_bus_runtime import DeliveryPayload, EventBusConfig
    from .json_types import JsonObject
    from .scheduler_cell_directory import SchedulerCellObservation
    from .scheduler_incident_feed import SchedulerIncidentCursor, SchedulerIncidentFeedConfig
    from .testing_runtime import MonkeyPatch

_START_TIME = 1_788_278_400.0
_FLOAT_TOLERANCE = 1e-9


def _configure(monkeypatch: MonkeyPatch) -> None:
    def read_empty_directory(
        _config: SchedulerIncidentFeedConfig,
    ) -> tuple[SchedulerCellObservation, ...]:
        return ()

    configure_event_bus(monkeypatch)
    monkeypatch.setenv("PITCHAI_PLATFORM_CENTRAL_URL", "https://platform.pitchai.net")
    monkeypatch.setenv("PITCHAI_PLATFORM_USER_TOKEN", TOKEN)
    monkeypatch.setattr(observer_module, "read_scheduler_cell_directory", read_empty_directory)


def test_feed_config_requires_secure_origin_and_bounded_token() -> None:
    """Accept HTTPS or exact loopback HTTP while rejecting remote plaintext."""
    config = load_scheduler_incident_feed_config(
        {
            "PITCHAI_PLATFORM_CENTRAL_URL": "https://platform.pitchai.net/",
            "PITCHAI_PLATFORM_USER_TOKEN": TOKEN,
        },
    )
    if config.url != "https://platform.pitchai.net/internal/global-api/v2/scheduler/new-lane-transitions":
        pytest.fail(f"unexpected scheduler feed URL: {config.url}")
    if config.directory_url != "https://platform.pitchai.net/internal/global-api/v2/directory":
        pytest.fail(f"unexpected scheduler directory URL: {config.directory_url}")

    loopback = load_scheduler_incident_feed_config(
        {
            "PITCHAI_PLATFORM_CENTRAL_URL": "http://127.0.0.1:18129",
            "PITCHAI_PLATFORM_USER_TOKEN": TOKEN,
        },
    )
    if loopback.directory_url != "http://127.0.0.1:18129/internal/global-api/v2/directory":
        pytest.fail(f"unexpected loopback scheduler directory URL: {loopback.directory_url}")

    for rejected_origin in ("http://platform.pitchai.net", "http://127.0.0.1.example:18129"):
        with pytest.raises(RuntimeError):
            _ = load_scheduler_incident_feed_config(
                {
                    "PITCHAI_PLATFORM_CENTRAL_URL": rejected_origin,
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
    directory_polled_at = float_value(state.get("last_successful_directory_poll_at_ts"))
    if directory_polled_at is None or abs(directory_polled_at - (_START_TIME + 1.0)) > _FLOAT_TOLERANCE:
        pytest.fail("central cell-directory poll was not checkpointed")
    if TOKEN in state_path.read_text(encoding="utf-8"):
        pytest.fail("scheduler observer persisted its bearer token")

    payload = captured[-1]
    if payload.get("event_kind") != "production_failure":
        pytest.fail(f"unexpected receiver event: {payload}")
    if "Telegram" in state_path.read_text(encoding="utf-8"):
        pytest.fail("scheduler observer state contains a direct notification route")


def test_observer_delivers_linked_recovery_after_completed_create(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Advance the same durable cursor from failure through proven recovery."""
    _configure(monkeypatch)
    state_path = tmp_path / "scheduler-observer.json"
    captured: list[JsonObject] = []
    reads = 0

    def read_page(
        _config: SchedulerIncidentFeedConfig,
        cursor: SchedulerIncidentCursor,
    ) -> SchedulerIncidentPage:
        nonlocal reads
        reads += 1
        payload = incident_feed() if reads == 1 else recovery_feed()
        return scheduler_incident_page(payload, prior_cursor=cursor)

    monkeypatch.setattr(observer_module, "read_scheduler_incident_page", read_page)
    transport = accepted_requests(captured)
    _ = run_cycle(state_path=state_path, now=_START_TIME, transport=transport)
    failed = run_cycle(state_path=state_path, now=_START_TIME + 1.0, transport=transport)
    recovered = run_cycle(state_path=state_path, now=_START_TIME + 2.0, transport=transport)

    kinds = [payload.get("event_kind") for payload in captured]
    if failed.delivered_count != 1 or recovered.delivered_count != 1 or kinds != [
        "production_failure",
        "production_recovered",
    ]:
        pytest.fail(f"observer did not deliver one linked failure/recovery pair: {failed}, {recovered}, {kinds}")
    failure_details = optional_object(captured[0].get("details"))
    recovery_details = optional_object(captured[1].get("details"))
    if failure_details.get("incident_fingerprint") != recovery_details.get("incident_fingerprint"):
        pytest.fail("observer recovery changed the original incident fingerprint")
    if optional_object(load_state(state_path).get("cursor")).get("event_id") != RECOVERY_EVENT_ID:
        pytest.fail("observer did not checkpoint the recovery cursor")


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


def test_observer_delivers_cell_liveness_failure_from_central_directory(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Join the canonical directory observer to the same durable receiver path."""
    _configure(monkeypatch)
    state_path = tmp_path / "scheduler-observer.json"
    captured: list[JsonObject] = []
    stale_at = _START_TIME + 360.0

    def read_empty_page(
        _config: SchedulerIncidentFeedConfig,
        cursor: SchedulerIncidentCursor,
    ) -> SchedulerIncidentPage:
        return SchedulerIncidentPage(events=(), next_cursor=cursor)

    def read_stale_directory(
        _config: SchedulerIncidentFeedConfig,
    ) -> tuple[SchedulerCellObservation, ...]:
        return (cell_observation(now=stale_at, last_received_at=_START_TIME),)

    monkeypatch.setattr(observer_module, "read_scheduler_incident_page", read_empty_page)
    monkeypatch.setattr(
        observer_module,
        "read_scheduler_cell_directory",
        read_stale_directory,
    )
    _ = run_cycle(state_path=state_path, now=_START_TIME, transport=accepted_requests(captured))
    receipt = run_cycle(state_path=state_path, now=stale_at, transport=accepted_requests(captured))

    if receipt.observed_count != 1 or receipt.delivered_count != 1:
        pytest.fail(f"cell liveness transition did not reach the receiver: {receipt}")
    if captured[-1].get("event_kind") != "production_failure":
        pytest.fail("cell liveness transition used the wrong receiver event kind")
    details = optional_object(captured[-1].get("details"))
    if details.get("surface_kind") != "cell_liveness" or details.get("site") != "dev-jeff-cell-two":
        pytest.fail(f"cell liveness receiver evidence was malformed: {details}")
