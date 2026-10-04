# Copyright (c) 2026 PitchAI. All rights reserved.
"""Disposable signed-delivery, lost-ACK and stale-lease acceptance proof."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from functools import partial
from typing import TYPE_CHECKING, cast, final

import pytest
from httpx import MockTransport, Response

from domain_checks.event_bus import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    EventBusConfig,
    signature_for_delivery,
)
from domain_checks.event_bus_delivery import deliver_event_bus_payload

from .completion_capture import RegistrySource, install_capture
from .completion_delivery import claim_completion, deliver_completion, record_completion_receipt
from .hotpath_codec import decode_object
from .test_completion_capture import expect_equal

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import Request

    from .test_completion_capture import Evidence


@final
@pytest.mark.usefixtures("setup_registry")
class TestCompletionDelivery:
    """Exercise real durable payloads and the existing signed gateway offline."""

    path: str = ""
    config: EventBusConfig = EventBusConfig("https://events.invalid/webhook", "disposable-test-secret-only" * 2,
                                           "test", "disposable", None)

    @pytest.fixture
    def setup_registry(self, tmp_path: Path) -> None:
        """Create exactly one private original completion, without a live runner."""
        self.path = str(tmp_path / "source.db")
        with closing(sqlite3.connect(self.path)) as connection:
            _ = connection.executescript("""
                CREATE TABLE tests(id TEXT PRIMARY KEY,tenant_id TEXT,name TEXT);
                CREATE TABLE runs(id TEXT PRIMARY KEY,test_id TEXT,status TEXT,started_at_ts REAL,
                    finished_at_ts REAL,elapsed_ms INTEGER,error_kind TEXT,error_message TEXT,
                    final_url TEXT,title TEXT,artifacts_json TEXT);
                INSERT INTO tests VALUES('canary','registry-owner','Original canary');
                INSERT INTO runs(id,test_id,status,error_kind,artifacts_json)
                    VALUES('run','canary','infra_degraded','pending','{}');
            """)
        install_capture(self.path, (RegistrySource("registry-owner", "canary"),))
        with closing(sqlite3.connect(self.path)) as connection, connection as transaction:
            _ = transaction.execute("""UPDATE runs SET status='fail',finished_at_ts=1000,
                error_kind='answer',error_message='Full failed answer: café' WHERE id='run'""")

    def test_lost_ack_restart_reuses_signed_original_and_fences_stale_receipt(self) -> None:
        """Receiver dedupe sees identical bytes; an expired sender cannot settle a newer lease."""
        first = claim_completion(self.path, self.config, now=100)
        if first is None:
            pytest.fail("Original completion was not claimable")
        expect_equal(claim_completion(self.path, self.config, now=101) is None, expected=True)
        received: list[str] = []

        def receiver(request: Request) -> Response:
            delivery_id = request.headers[DELIVERY_HEADER]
            expect_equal(request.headers[EVENT_HEADER], "registry_run_complete")
            expect_equal(request.headers[SIGNATURE_HEADER], signature_for_delivery(
                body=request.content, secret=self.config.secret,
                timestamp=request.headers[TIMESTAMP_HEADER], delivery_id=delivery_id,
                event_kind=request.headers[EVENT_HEADER],
            ))
            received.append(request.content.decode())
            response_factory = partial(Response, 202, json={"accepted": 1, "event_ids": ["same-receiver-event"]})
            return response_factory()

        transport_factory = partial(MockTransport, receiver)
        with transport_factory() as transport:
            first_ack = deliver_event_bus_payload(self.config, decode_object(first.payload_json), transport=transport)
            # Crash here loses this ACK, retaining the already persisted payload.
            second = claim_completion(self.path, self.config, now=221)
            if second is None:
                pytest.fail("Expired original claim did not recover")
            second_ack = deliver_event_bus_payload(self.config, decode_object(second.payload_json), transport=transport)
        expect_equal(first_ack.event_id, second_ack.event_id)
        expect_equal(received[0], received[1])
        payload = cast("dict[str, Evidence]", json.loads(received[1]))
        details = cast("dict[str, Evidence]", payload["details"])
        expect_equal(details["registry_tenant_id"], "registry-owner")
        expect_equal(details["registry_test_id"], "canary")
        expect_equal(details["registry_run_id"], "run")
        expect_equal(details["error_message"], "Full failed answer: café")
        expect_equal(record_completion_receipt(
            self.path, first, event_id=first_ack.event_id, error=None, now=222,
        ), expected=False)
        expect_equal(record_completion_receipt(
            self.path, second, event_id=second_ack.event_id, error=None, now=222,
        ), expected=True)
        expect_equal(claim_completion(self.path, self.config, now=1000) is None, expected=True)

    def test_receiver_rejection_keeps_original_pending(self) -> None:
        """A rejected kind or unavailable receiver is not successful delivery."""
        work = claim_completion(self.path, self.config, now=100)
        if work is None:
            pytest.fail("Original completion was not claimable")

        def unavailable(_request: Request) -> Response:
            response_factory = partial(Response, 503)
            return response_factory()

        transport_factory = partial(MockTransport, unavailable)
        with transport_factory() as transport:
            receipt = deliver_event_bus_payload(self.config, decode_object(work.payload_json), transport=transport)
        expect_equal(receipt.success, expected=False)
        expect_equal(record_completion_receipt(
            self.path, work, event_id=None, error=receipt.error, now=101,
        ), expected=True)
        expect_equal(claim_completion(self.path, self.config, now=102) is None, expected=True)
        retry = claim_completion(self.path, self.config, now=132)
        if retry is None:
            pytest.fail("Rejected delivery lost its obligation")
        expect_equal(retry.payload_json, work.payload_json)
        expect_equal(retry.attempt, 2)

    @pytest.mark.asyncio
    async def test_async_sender_records_only_real_receiver_acceptance(self) -> None:
        """The installed delivery coroutine uses the gateway and settles its lease."""
        work = claim_completion(self.path, self.config, now=100)
        if work is None:
            pytest.fail("Original completion was not claimable")

        def receiver(_request: Request) -> Response:
            response_factory = partial(Response, 202, json={"accepted": 1, "event_ids": ["durable-event"]})
            return response_factory()

        transport_factory = partial(MockTransport, receiver)
        with transport_factory() as transport:
            settled = await deliver_completion(self.path, self.config, work, transport=transport)
        expect_equal(settled, expected=True)
        expect_equal(claim_completion(self.path, self.config, now=1000) is None, expected=True)
        with closing(sqlite3.connect(self.path)) as connection:
            row = cast("tuple[Evidence, ...]", connection.execute(
                "SELECT receiver_event_id, lease_token, last_error FROM registry_completion_outbox",
            ).fetchone())
        expect_equal(row, ("durable-event", None, None))

    @pytest.mark.asyncio
    async def test_async_sender_does_not_consume_invalid_acceptance(self) -> None:
        """HTTP success without exactly one event receipt remains retryable."""
        work = claim_completion(self.path, self.config, now=100)
        if work is None:
            pytest.fail("Original completion was not claimable")

        def receiver(_request: Request) -> Response:
            response_factory = partial(Response, 202, json={"accepted": 0, "event_ids": []})
            return response_factory()

        transport_factory = partial(MockTransport, receiver)
        with transport_factory() as transport:
            recorded = await deliver_completion(self.path, self.config, work, transport=transport)
        expect_equal(recorded, expected=True)
        with closing(sqlite3.connect(self.path)) as connection:
            row = cast("tuple[Evidence, ...]", connection.execute(
                "SELECT receiver_event_id, last_error FROM registry_completion_outbox",
            ).fetchone())
        expect_equal(row, (None, "invalid_acceptance_response"))
