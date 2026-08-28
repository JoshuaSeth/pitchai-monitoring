# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reusable deterministic fixtures for critical incident sidecar tests."""

from __future__ import annotations

import hashlib
import json
from functools import partial
from typing import TYPE_CHECKING, cast

from httpx import MockTransport, Response

from .json_types import json_object

if TYPE_CHECKING:
    from httpx import Request

    from .json_types import JsonInput, JsonObject
    from .testing_runtime import MonkeyPatch

EVENT_TIME = 1_787_860_800.0
REESCALATION_SECONDS = 1_861.0
ACCEPTED_STATUS = 202


def configure_event_bus(monkeypatch: MonkeyPatch) -> None:
    """Install non-secret deterministic Events Bus test configuration."""
    signing_key = hashlib.sha256(b"domain-event-bus-test-key").hexdigest()
    monkeypatch.setenv(
        "PITCHAI_MONITORING_EVENT_BUS_URL",
        "https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
    )
    monkeypatch.setenv("PITCHAI_MONITORING_EVENT_BUS_SECRET", signing_key)
    monkeypatch.setenv("PITCHAI_MONITORING_ENVIRONMENT", "production")
    monkeypatch.setenv("PITCHAI_MONITORING_INSTANCE", "pytest-domain-events")


def domain_down_state() -> JsonObject:
    """Return one debounced critical Unimix domain failure fixture."""
    return json_object(
        cast(
            "JsonInput",
            {
                "version": 6,
                "updated_at": "2026-08-28T00:00:00Z",
                "last_ok": {"unimixbrasil.com.br": False},
                "events": [
                    {
                        "ts": EVENT_TIME,
                        "kind": "domain_down",
                        "domain": "unimixbrasil.com.br",
                        "reason": "http_status_503",
                        "status_code": 503,
                        "fail_streak": 2,
                        "telegram_alert": True,
                    },
                ],
            },
        ),
    )


def production_failure_state() -> JsonObject:
    """Return one debounced critical SkyBuyFly transaction failure fixture."""
    return json_object(
        cast(
            "JsonInput",
            {
                "version": 6,
                "last_ok": {"skybuyfly.pitchai.net": True},
                "synthetic": {"last_ok": {"skybuyfly.pitchai.net": False}},
                "proxy": {"last_ok": True},
                "events": [
                    {
                        "ts": EVENT_TIME,
                        "kind": "synthetic_degraded",
                        "domain": "skybuyfly.pitchai.net",
                        "failures": 2,
                        "telegram_alert": True,
                    },
                ],
            },
        ),
    )


def accepted_requests(captured: list[JsonObject]) -> MockTransport:
    """Return a receiver transport that captures and accepts one delivery."""

    def _accepted(request: Request) -> Response:
        decoded = cast("JsonInput", json.loads(request.content.decode()))
        payload = json_object(decoded)
        captured.append(payload)
        delivery_id = cast("str", request.headers.get("X-PitchAI-Monitoring-Delivery", ""))
        receiver_event_id = f"domain-event-for-{delivery_id}"
        response_factory = partial(
            Response,
            ACCEPTED_STATUS,
            request=request,
            json={"accepted": 1, "event_ids": [receiver_event_id]},
        )
        return response_factory()

    transport_factory = partial(MockTransport, _accepted)
    return transport_factory()
