# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove the shared immutable-envelope delivery gateway."""

from __future__ import annotations

import hashlib
import json
from functools import partial
from typing import TYPE_CHECKING, cast

from httpx import MockTransport, Response

from e2e_registry.hotpath_event_bus_runtime import EventBusConfig as HotpathEventBusConfig
from e2e_registry.hotpath_event_gateway import EventWork, deliver_event

from .event_bus_runtime import DELIVERY_RUNTIME, EventBusConfig
from .json_types import optional_object, text_value
from .testing_runtime import pytest

if TYPE_CHECKING:
    from httpx import Request

_EVENT_TIME = 1_787_855_200.0
_DELIVERY_TIME = _EVENT_TIME + 1.0
_ACCEPTED_STATUS = 202


def _config() -> EventBusConfig:
    signing_key = hashlib.sha256(b"monitoring-delivery-test-key").hexdigest()
    return EventBusConfig(
        webhook_url="https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
        secret=signing_key,
        environment="production",
        instance="pytest-monitoring",
        deployment_sha="a" * 40,
    )


def _accepted(request: Request) -> Response:
    delivery_id = cast("str", request.headers.get("X-PitchAI-Monitoring-Delivery", ""))
    signature = cast("str", request.headers.get("X-PitchAI-Monitoring-Signature-256", ""))
    valid = bool(delivery_id.startswith("monitoring-") and signature.startswith("sha256="))
    status_code = _ACCEPTED_STATUS if valid else 400
    response_factory = partial(
        Response,
        status_code,
        request=request,
        json={"accepted": 1, "event_ids": [f"event-for-{delivery_id}"]},
    )
    return response_factory()


def test_gateway_preserves_delivery_identity_and_receiver_dedupe_key() -> None:
    """Deliver one hotpath RED envelope without rebuilding its identity."""
    config = _config()
    payload = DELIVERY_RUNTIME.build_incident_payload(
        config,
        kind="hotpath_red",
        occurred_at=_EVENT_TIME,
        details={
            "hotpath_id": "safe-synthetic-proof",
            "severity": "critical",
            "synthetic": True,
        },
    )
    transport_factory = partial(MockTransport, _accepted)
    attempt = DELIVERY_RUNTIME.deliver_event_bus_payload(
        config,
        payload,
        now=_DELIVERY_TIME,
        transport=transport_factory(),
    )

    delivery_id = text_value(payload.get("delivery_id"))
    if not attempt.success:
        pytest.fail(f"shared Events Bus gateway rejected a valid payload: {attempt.error}")
    if attempt.delivery_id != delivery_id:
        pytest.fail("gateway replaced the producer delivery identity")
    if attempt.event_id != f"event-for-{delivery_id}":
        pytest.fail("gateway did not retain the receiver event id")


def test_gateway_rejects_payload_mutation_before_network_delivery() -> None:
    """Fail a tampered envelope before its stale delivery id can be reused."""
    config = _config()
    payload = DELIVERY_RUNTIME.build_incident_payload(
        config,
        kind="hotpath_red",
        occurred_at=_EVENT_TIME,
        details={"hotpath_id": "safe-synthetic-proof", "severity": "critical"},
    )
    details = optional_object(payload.get("details"))
    details["hotpath_id"] = "mutated-after-persistence"
    payload["details"] = details
    transport_factory = partial(MockTransport, _accepted)

    with pytest.raises(ValueError):
        _ = DELIVERY_RUNTIME.deliver_event_bus_payload(
            config,
            payload,
            now=_DELIVERY_TIME,
            transport=transport_factory(),
        )


@pytest.mark.asyncio
async def test_hotpath_adapter_uses_the_strict_shared_gateway() -> None:
    """Keep hotpath outbox delivery bound to the final shared module path."""
    config = _config()
    payload = DELIVERY_RUNTIME.build_incident_payload(
        config,
        kind="hotpath_red",
        occurred_at=_EVENT_TIME,
        details={
            "hotpath_id": "safe-synthetic-proof",
            "severity": "critical",
            "synthetic": True,
        },
    )
    delivery_id = text_value(payload.get("delivery_id"))
    hotpath_config = HotpathEventBusConfig(
        config.webhook_url,
        config.secret,
        config.environment,
        config.instance,
        config.deployment_sha,
        config.timeout_seconds,
    )
    work = EventWork(
        intent_id="hotpath-intent-safe-synthetic-proof",
        event_kind="hotpath_red",
        delivery_id=delivery_id,
        payload_json=json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
    )
    transport_factory = partial(MockTransport, _accepted)

    result = await deliver_event(
        hotpath_config,
        work,
        now_ts=_DELIVERY_TIME,
        transport=transport_factory(),
    )

    if result.error is not None or result.event_id != f"event-for-{delivery_id}":
        pytest.fail(f"hotpath adapter did not reach the shared gateway: {result}")
