# Copyright (c) 2026 PitchAI. All rights reserved.
"""Event-bus environment configuration checks."""

import pytest

from domain_checks.event_bus import load_event_bus_config
from domain_checks.testing import verify
from tests.event_bus_support import DEPLOYMENT_SHA, EVENT_BUS_KEY_MATERIAL


def test_load_event_bus_config_is_optional_but_partial_configuration_fails_loudly() -> None:
    """Verify partial event-bus configuration fails loudly."""
    verify(load_event_bus_config({}) is None)

    with pytest.raises(RuntimeError, match=r"Both .*URL and secret"):
        _ = load_event_bus_config({"PITCHAI_MONITORING_EVENT_BUS_URL": "https://example.test/hook"})

    with pytest.raises(RuntimeError, match="HTTPS URL"):
        _ = load_event_bus_config(
            {
                "PITCHAI_MONITORING_EVENT_BUS_URL": "http://example.test/hook",
                "PITCHAI_MONITORING_EVENT_BUS_SECRET": EVENT_BUS_KEY_MATERIAL,
            },
        )

    with pytest.raises(RuntimeError, match="at least 32"):
        _ = load_event_bus_config(
            {
                "PITCHAI_MONITORING_EVENT_BUS_URL": "https://example.test/hook",
                "PITCHAI_MONITORING_EVENT_BUS_SECRET": "short",
            },
        )


def test_load_event_bus_config_validates_routing_identity_and_timeout() -> None:
    """Verify event-bus routing identity and timeout validation."""
    base = {
        "PITCHAI_MONITORING_EVENT_BUS_URL": "https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
        "PITCHAI_MONITORING_EVENT_BUS_SECRET": EVENT_BUS_KEY_MATERIAL,
    }

    with pytest.raises(RuntimeError, match="ENVIRONMENT"):
        _ = load_event_bus_config({**base, "PITCHAI_MONITORING_ENVIRONMENT": "Not Valid"})
    with pytest.raises(RuntimeError, match="INSTANCE"):
        _ = load_event_bus_config({**base, "PITCHAI_MONITORING_INSTANCE": "bad value"})
    with pytest.raises(RuntimeError, match="40-byte SHA"):
        _ = load_event_bus_config({**base, "PITCHAI_MONITORING_DEPLOYMENT_SHA": "short"})
    with pytest.raises(RuntimeError, match="between 1 and 60"):
        _ = load_event_bus_config({**base, "PITCHAI_MONITORING_EVENT_BUS_TIMEOUT_SECONDS": "0"})

    config = load_event_bus_config(
        {
            **base,
            "PITCHAI_MONITORING_ENVIRONMENT": "production",
            "PITCHAI_MONITORING_INSTANCE": "pitchai-main",
            "PITCHAI_MONITORING_DEPLOYMENT_SHA": DEPLOYMENT_SHA,
        },
    )
    if config is None:
        pytest.fail("complete Events Bus configuration was rejected")
    verify(config.environment == "production")
    verify(config.instance == "pitchai-main")
    verify(config.deployment_sha == DEPLOYMENT_SHA)
