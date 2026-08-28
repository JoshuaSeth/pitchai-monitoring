# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove one production owner delivers each domain/app incident."""

from __future__ import annotations

from pathlib import Path

from .testing_runtime import pytest

_BUS_URL_ENV = "PITCHAI_MONITORING_EVENT_BUS_URL"
_BUS_CREDENTIAL_ENV = "PITCHAI_MONITORING_EVENT_BUS_SECRET"


def test_production_collector_delegates_critical_delivery_to_the_sidecar() -> None:
    """Keep Telegram local while the enriched sidecar owns domain/app delivery."""
    workflow = Path(".github/workflows/ci-cd.yaml").read_text(encoding="utf-8")
    service_tail = workflow.split('echo "🚀 Starting service-monitoring..."', maxsplit=1)[1]
    service_block, domain_tail = service_tail.split(
        'echo "🚀 Starting domain incident Events Bus producer..."',
        maxsplit=1,
    )
    domain_block = domain_tail.split(
        'echo "🚀 Starting database dependency monitor..."',
        maxsplit=1,
    )[0]

    if _BUS_URL_ENV in service_block or _BUS_CREDENTIAL_ENV in service_block:
        pytest.fail("legacy service-monitoring must not emit incomplete critical incidents")
    if _BUS_URL_ENV not in domain_block or _BUS_CREDENTIAL_ENV not in domain_block:
        pytest.fail("dedicated domain incident sidecar is missing Events Bus delivery")


def test_deployment_proves_single_owner_configuration_at_runtime() -> None:
    """Require the deploy gate to prove the legacy producer is off and critical producers are on."""
    workflow = Path(".github/workflows/ci-cd.yaml").read_text(encoding="utf-8")
    disabled_probe = "assert load_event_bus_config() is None'"
    enabled_containers = ("REGISTRY_NAME", "DOMAIN_EVENT_NAME", "DB_MONITOR_NAME")

    if disabled_probe not in workflow:
        pytest.fail("deploy gate does not prove the legacy producer is disabled")
    for container_name in enabled_containers:
        enabled_probe = f'docker exec "${container_name}" python -c'
        if enabled_probe not in workflow:
            pytest.fail(f"deploy gate does not prove {container_name} Events Bus delivery")
