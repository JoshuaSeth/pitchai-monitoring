# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test event bus behavior."""

from __future__ import annotations

import hashlib
import hmac
import json
import math

import httpx
import pytest

from domain_checks.event_bus import (
    MONITORING_EVENT_KINDS,
    EventBusOutbox,
    build_payload,
    signature_for_delivery,
)
from domain_checks.testing import verify
from tests.event_bus_support import DEPLOYMENT_SHA, EVENT_BUS_KEY_MATERIAL, event_bus_config

HTTP_ACCEPTED = 202
HTTP_SERVICE_UNAVAILABLE = 503
EXPECTED_NEXT_ATTEMPT = 102.0


def _accepted(request: httpx.Request) -> httpx.Response:
    delivery_id = request.headers["X-PitchAI-Monitoring-Delivery"]
    return httpx.Response(
        HTTP_ACCEPTED,
        json={"accepted": 1, "event_ids": [f"event-for-{delivery_id}"]},
        request=request,
    )


def test_payload_identity_is_deterministic_strict_json_and_excludes_secret() -> None:
    """Verify payload identity is deterministic strict json and excludes secret."""
    config = event_bus_config()
    first = build_payload(
        config,
        kind="domain_down",
        occurred_at=1_784_001_600.25,
        details={"domain": "internal.pitchai.net", "status_code": 503},
    )
    second = build_payload(
        config,
        kind="domain_down",
        occurred_at=1_784_001_600.25,
        details={"status_code": 503, "domain": "internal.pitchai.net"},
    )

    verify(first == second)
    verify(first["delivery_id"].startswith("monitoring-"))
    verify(
        first["source"]
        == {
            "service": "service-monitoring",
            "environment": "production",
            "instance": "pitchai-main",
            "deployment_sha": DEPLOYMENT_SHA,
        },
    )
    verify(EVENT_BUS_KEY_MATERIAL not in json.dumps(first, sort_keys=True))

    with pytest.raises(ValueError, match="strict JSON"):
        _ = build_payload(config, kind="domain_down", occurred_at=1.0, details={"bad": float("nan")})


@pytest.mark.parametrize("event_kind", sorted(MONITORING_EVENT_KINDS))
def test_every_supported_event_kind_builds_a_stable_envelope(event_kind: str) -> None:
    """Verify every supported event kind builds a stable envelope."""
    payload = build_payload(
        event_bus_config(),
        kind=event_kind,
        occurred_at=1_784_001_600.0,
        details={"probe_label": "catalog-test"},
    )

    verify(payload["event_kind"] == event_kind)
    verify(payload["delivery_id"].startswith("monitoring-"))


def test_signature_binds_timestamp_delivery_event_and_body() -> None:
    """Verify signature binds timestamp delivery event and body."""
    body = b'{"example":true}'
    signature = signature_for_delivery(
        body=body,
        secret=EVENT_BUS_KEY_MATERIAL,
        timestamp="1784001600",
        delivery_id="monitoring-example",
        event_kind="integration_test",
    )
    signed = b"v1\n1784001600\nmonitoring-example\nintegration_test\n" + body
    expected = hmac.new(EVENT_BUS_KEY_MATERIAL.encode(), signed, hashlib.sha256).hexdigest()

    verify(signature == f"sha256={expected}")


@pytest.mark.asyncio
async def test_successful_delivery_removes_outbox_entry_and_sends_required_headers() -> None:
    """Verify successful delivery removes outbox entry and sends required headers."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _accepted(request)

    outbox = EventBusOutbox(event_bus_config())
    delivery_id = outbox.enqueue(
        "integration_test",
        occurred_at=1_784_001_600.0,
        details={"probe_label": "pytest"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempts = await outbox.flush(client, now=1_784_001_601.0)

    verify(len(attempts) == 1)
    verify(attempts[0].success is True)
    verify(attempts[0].delivery_id == delivery_id)
    verify(attempts[0].event_id == f"event-for-{delivery_id}")
    verify(outbox.pending_count == 0)
    verify(seen[0].headers["X-PitchAI-Monitoring-Delivery"] == delivery_id)
    verify(seen[0].headers["X-PitchAI-Monitoring-Event"] == "integration_test")
    verify(seen[0].headers["X-PitchAI-Monitoring-Timestamp"] == "1784001601")
    verify(seen[0].headers["X-PitchAI-Monitoring-Signature-256"].startswith("sha256="))


@pytest.mark.asyncio
async def test_failure_is_persisted_and_retried_after_backoff() -> None:
    """Verify failure is persisted and retried after backoff."""
    statuses = [HTTP_SERVICE_UNAVAILABLE, HTTP_ACCEPTED]

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        if status == HTTP_ACCEPTED:
            return _accepted(request)
        return httpx.Response(status, request=request)

    outbox = EventBusOutbox(event_bus_config())
    delivery_id = outbox.enqueue(
        "domain_down",
        occurred_at=1_784_001_600.0,
        details={"domain": "internal.pitchai.net"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await outbox.flush(client, now=100.0)
        too_soon = await outbox.flush(client, now=101.0)
        persisted = outbox.to_state()
        reloaded = EventBusOutbox(event_bus_config(), entries=persisted)
        second = await reloaded.flush(client, now=102.0)

    verify(first[0].success is False)
    verify(first[0].status_code == HTTP_SERVICE_UNAVAILABLE)
    verify(too_soon == [])
    verify(persisted[0]["attempts"] == 1)
    verify(persisted[0]["last_error"] == "http_status_503")
    next_attempt_at = persisted[0]["next_attempt_at"]
    verify(math.isclose(float(next_attempt_at), EXPECTED_NEXT_ATTEMPT))
    verify(EVENT_BUS_KEY_MATERIAL not in json.dumps(persisted, sort_keys=True))
    verify(second[0].success is True)
    verify(second[0].delivery_id == delivery_id)
    verify(reloaded.pending_count == 0)


@pytest.mark.asyncio
async def test_network_and_invalid_acceptance_responses_remain_pending() -> None:
    """Verify network and invalid acceptance responses remain pending."""

    def network_failure(request: httpx.Request) -> httpx.Response:
        msg = "unavailable"
        raise httpx.ConnectError(msg, request=request)

    outbox = EventBusOutbox(event_bus_config())
    _ = outbox.enqueue("service_started", occurred_at=1.0, details={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(network_failure)) as client:
        attempt = (await outbox.flush(client, now=10.0))[0]
    verify(attempt.error == "ConnectError")
    verify(outbox.pending_count == 1)

    invalid = EventBusOutbox(event_bus_config())
    _ = invalid.enqueue("service_started", occurred_at=2.0, details={})
    transport = httpx.MockTransport(
        lambda request: httpx.Response(HTTP_ACCEPTED, json={}, request=request),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        attempt = (await invalid.flush(client, now=10.0))[0]
    verify(attempt.error == "invalid_acceptance_response")
    verify(invalid.pending_count == 1)
