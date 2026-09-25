# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared event-bus test configuration."""

from domain_checks.event_bus import EventBusConfig

EVENT_BUS_KEY_MATERIAL = "test-monitoring-event-bus-secret-that-is-long-enough"
DEPLOYMENT_SHA = "a" * 40


def event_bus_config() -> EventBusConfig:
    """Build a valid production-shaped event-bus configuration.

    Returns:
        A deterministic event-bus configuration for tests.
    """
    return EventBusConfig(
        webhook_url="https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
        secret=EVENT_BUS_KEY_MATERIAL,
        environment="production",
        instance="pitchai-main",
        deployment_sha=DEPLOYMENT_SHA,
        timeout_seconds=10.0,
    )
