# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable facade and CLI for durable monitoring event delivery."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx

from domain_checks.event_bus_config import load_event_bus_config
from domain_checks.event_bus_delivery import EventBusOutbox
from domain_checks.event_bus_models import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    MONITORING_EVENT_KINDS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    DeliveryAttempt,
    EventBusConfig,
    EventOutboxState,
    EventPayload,
)
from domain_checks.event_bus_payloads import build_payload, signature_for_delivery

__all__ = [
    "DELIVERY_HEADER",
    "EVENT_HEADER",
    "MONITORING_EVENT_KINDS",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "DeliveryAttempt",
    "EventBusConfig",
    "EventBusOutbox",
    "EventOutboxState",
    "EventPayload",
    "build_payload",
    "load_event_bus_config",
    "signature_for_delivery",
]


async def _send_probe(config: EventBusConfig, probe_label: str) -> DeliveryAttempt:
    outbox = EventBusOutbox(config)
    _ = outbox.enqueue(
        "integration_test",
        occurred_at=time.time(),
        details={"probe_label": probe_label[:240]},
    )
    async with httpx.AsyncClient(
        headers={"User-Agent": "PitchAI Service Monitoring"},
    ) as client:
        attempts = await outbox.flush(client)
    if len(attempts) != 1 or not attempts[0].success or outbox.pending_count:
        message = "PitchAI monitoring Events Bus probe was not accepted"
        raise RuntimeError(message)
    return attempts[0]


def main() -> int:
    """Run the explicit Events Bus integration probe CLI.

    Returns:
        Zero after the probe is accepted and reported.

    Raises:
        RuntimeError: Delivery is not configured or the probe is rejected.
        TypeError: The parsed probe label is not text.
    """
    parser = argparse.ArgumentParser(
        description="PitchAI monitoring Events Bus delivery probe",
    )
    _ = parser.add_argument(
        "--probe-label",
        required=True,
        help="Non-sensitive internal probe label",
    )
    arguments = vars(parser.parse_args())
    probe_label = arguments.get("probe_label")
    if not isinstance(probe_label, str):
        message = "--probe-label must be text"
        raise TypeError(message)
    config = load_event_bus_config()
    if config is None:
        message = "PitchAI monitoring Events Bus delivery is not configured"
        raise RuntimeError(message)
    with asyncio.Runner() as runner:
        attempt = runner.run(_send_probe(config, probe_label))
    _ = sys.stdout.write(
        json.dumps(
            {
                "accepted": attempt.success,
                "delivery_id": attempt.delivery_id,
                "event_id": attempt.event_id,
                "status_code": attempt.status_code,
            },
            sort_keys=True,
        )
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
