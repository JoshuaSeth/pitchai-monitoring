# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed fixtures shared by database dependency monitoring tests."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import re
import runpy
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast
from unittest.mock import patch

import pytest

from domain_checks.database_dependencies.models import (
    DatabaseDependencySettings,
    ProbeDefinition,
    ProbeObservation,
)
from domain_checks.database_dependencies.state import reduce_state
from domain_checks.monitoring_contracts.json_types import json_object

if TYPE_CHECKING:
    from domain_checks.database_dependencies.models import (
        ConnectionMode,
        ProbeRule,
        TrafficState,
    )
    from domain_checks.monitoring_contracts.json_types import JsonInput, JsonObject

ROOT = Path(__file__).resolve().parents[1]
_TARGET_PROBE_PATH = ROOT / "domain_checks/database_dependencies/target_probe.txt"


class DefinitionOptions(NamedTuple):
    """Optional variations for a concrete dependency fixture."""

    alert_group: str = "app-database"
    critical: bool = True
    traffic_state: TrafficState = "active"
    route_eligible: bool = True
    mode: ConnectionMode = "psycopg_url"
    environment_keys: tuple[str, ...] = ("DATABASE_URL",)
    sync_driver: str | None = "psycopg"
    relation_checks: tuple[str, ...] = ("example_rows",)
    schema_checks: tuple[str, ...] = ("public",)


_DEFAULT_DEFINITION_OPTIONS = DefinitionOptions()


def settings(*, rules: tuple[ProbeRule, ...] = ()) -> DatabaseDependencySettings:
    """Return a compact valid collector policy for unit tests."""
    return DatabaseDependencySettings(
        interval_seconds=300,
        timeout_seconds=4,
        down_after_failures=2,
        up_after_successes=2,
        max_parallel_probes=4,
        docker_socket_path="/var/run/docker.sock",
        state_path="/data/database-dependencies.json",
        python_executable="python",
        environment_key_patterns=(re.compile(r"^(?:DATABASE_URL|[A-Z0-9_]+_DB_PATH)$"),),
        environment_key_exclude_patterns=(),
        exclude_patterns=(),
        routing_policies=(),
        rules=rules,
    )


def definition(
    dependency_id: str,
    *,
    options: DefinitionOptions = _DEFAULT_DEFINITION_OPTIONS,
) -> ProbeDefinition:
    """Return one concrete production database dependency."""
    return ProbeDefinition(
        dependency_id=dependency_id,
        dependency_kind="database",
        container_id=f"container-{dependency_id}",
        container_name=f"container-{dependency_id}",
        app_name="Example app",
        owner_project="Example",
        environment="production",
        database_label="Runtime PostgreSQL",
        critical=options.critical,
        telegram_policy_enabled=options.critical,
        domains=("example.pitchai.net",),
        likely_fix_path="Restore the runtime database route.",
        mode=options.mode,
        environment_keys=options.environment_keys,
        file_environment_keys=(),
        default_credential_path=None,
        default_sqlite_path=None,
        engine_attr=None,
        engine_callable=False,
        sync_driver=options.sync_driver,
        relation_checks=options.relation_checks,
        schema_checks=options.schema_checks,
        coverage=("login/authentication", "schema usage", "configured table grants"),
        credential_source="runtime_environment",
        routing_policy_id="example-route" if options.traffic_state != "active" else None,
        traffic_slot="green" if options.traffic_state != "active" else None,
        traffic_state=options.traffic_state,
        traffic_weight=(
            0 if options.traffic_state == "inactive" else 100 if options.traffic_state == "active" else None
        ),
        routing_source="test",
        routing_error="routing_header_missing" if options.traffic_state == "unknown" else None,
        alert_group=options.alert_group,
        telegram_route_eligible=options.route_eligible,
        telegram_suppression_reason=None if options.route_eligible else f"{options.traffic_state}_slot",
    )


def observation(
    probe: ProbeDefinition,
    *,
    at: float,
    ok: bool,
    failure_class: str = "invalid_or_revoked_password",
    latency_ms: float = 12.5,
) -> ProbeObservation:
    """Return one sanitized test probe observation."""
    return ProbeObservation(
        dependency_id=probe.dependency_id,
        observed_at_ts=at,
        ok=ok,
        latency_ms=latency_ms,
        failure_class=None if ok else failure_class,
        failure_phase=None if ok else "connection",
        sqlstate=None if ok else "28P01",
        sanitized_error_excerpt=None if ok else "password authentication failed for role <redacted>",
    )


def cycle(
    definitions: list[ProbeDefinition],
    observations: list[ProbeObservation],
    *,
    previous: JsonObject | None = None,
    at: float,
) -> JsonObject:
    """Reduce one complete test collector cycle.

    Returns:
        The resulting compact collector state.
    """
    return reduce_state(
        definitions=definitions,
        observations=observations,
        previous={} if previous is None else previous,
        settings=settings(),
        generated_at_ts=at,
    )


def run_target_probe(probe: ProbeDefinition, *, database: Path) -> JsonObject:
    """Execute the self-contained in-container probe against a temporary SQLite DB.

    Returns:
        The probe's single normalized protocol object.
    """
    spec = {
        "mode": probe.mode,
        "environment_keys": list(probe.environment_keys),
        "file_environment_keys": [],
        "default_credential_path": None,
        "default_sqlite_path": None,
        "engine_attr": None,
        "engine_callable": False,
        "sync_driver": probe.sync_driver,
        "relation_checks": list(probe.relation_checks),
        "schema_checks": list(probe.schema_checks),
        "timeout_seconds": 2,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(spec).encode()).decode()
    output = io.StringIO()
    argv = [str(_TARGET_PROBE_PATH), encoded]
    with (
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(io.StringIO()),
        contextlib.chdir(ROOT),
        patch.object(sys, "argv", argv),
        patch.dict(os.environ, {"TEST_RUNTIME_DB_PATH": str(database)}),
    ):
        _ = runpy.run_path(str(_TARGET_PROBE_PATH), run_name="__main__")
    return json_object(cast("JsonInput", json.loads(output.getvalue())))


class InventoryGateway:
    """Fake Docker inventory that includes a credential value to reject."""

    def __init__(self) -> None:
        """Pin the only container id accepted by this fixture."""
        self._container_id: str = "container-id"

    def running_containers(self) -> list[JsonObject]:
        """Return one running production app."""
        return [{"Id": self._container_id, "Names": ["/owned-app"]}]

    def inspect_container(self, container_id: str) -> JsonObject:
        """Return environment metadata whose value must never leave discovery."""
        if container_id != self._container_id:
            pytest.fail("discovery inspected an unexpected container")
        return {
            "Config": {
                "Env": [
                    "DATABASE_URL=postgresql://runtime-user:never-retain-me@db.internal/app",
                    "UNRELATED=value",
                ],
            },
        }
