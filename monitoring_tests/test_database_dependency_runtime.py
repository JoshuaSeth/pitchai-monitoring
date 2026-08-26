# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exercise database discovery, probing, routing, and dashboard projection."""

from __future__ import annotations

import json
import math
import sqlite3
from functools import partial
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from httpx import Response

from monitoring_contracts.json_types import float_value, object_list
from monitoring_dashboard.databases import load_database_dashboard
from monitoring_dashboard.evidence import (
    bounded_response_body,
    require_public_endpoint,
)
from monitoring_database_dependencies.configuration import load_settings
from monitoring_database_dependencies.discovery import discover_dependencies
from monitoring_database_dependencies.failure_classification import classify_failure
from monitoring_database_dependencies.models import RoutingPolicy
from monitoring_database_dependencies.routing import resolve_routing
from monitoring_test_support.database_dependency import (
    ROOT,
    DefinitionOptions,
    InventoryGateway,
    cycle,
    definition,
    observation,
    run_target_probe,
    settings,
)
from monitoring_test_support.expectations import present

if TYPE_CHECKING:
    from pathlib import Path

_EXPECTED_EVIDENCE_BYTES = 8_192
_EXPECTED_REJECTED_STATUS = 409
_EXPECTED_SUCCESS_LATENCY_MS = 9.5


def test_sqlite_target_probe_is_read_only_bounded_and_reports_query_phase(
    tmp_path: Path,
) -> None:
    """Prove the target-side SQLite probe is read-only, bounded, and actionable."""
    database = tmp_path / "runtime.sqlite3"
    with sqlite3.connect(database) as connection:
        _ = connection.execute("CREATE TABLE present_rows (id INTEGER PRIMARY KEY)")
    probe = definition(
        "sqlite",
        options=DefinitionOptions(
            mode="sqlite",
            environment_keys=("TEST_RUNTIME_DB_PATH",),
            sync_driver=None,
            relation_checks=("present_rows",),
            schema_checks=(),
        ),
    )
    successful = run_target_probe(probe, database=database)
    if successful["ok"] is not True:
        pytest.fail("SQLite probe did not report success")

    missing_probe = definition(
        "sqlite",
        options=DefinitionOptions(
            mode="sqlite",
            environment_keys=("TEST_RUNTIME_DB_PATH",),
            sync_driver=None,
            relation_checks=("missing_rows",),
            schema_checks=(),
        ),
    )
    failed = run_target_probe(missing_probe, database=database)
    if failed["ok"] is not False:
        pytest.fail("missing SQLite table was not reported")
    if failed["error_kind"] != "missing_table_or_materialized_view":
        pytest.fail("missing SQLite table used the wrong failure class")
    if failed["phase"] != "query":
        pytest.fail("missing SQLite table used the wrong phase")
    if str(database) in json.dumps(failed):
        pytest.fail("probe leaked the SQLite path")


def test_failure_classification_covers_auth_grants_pgbouncer_and_timeout() -> None:
    """Classify the critical database failure families promised to operators."""
    if (
        classify_failure(
            kind="OperationalError",
            phase="connection",
            sqlstate="28P01",
            excerpt="",
        )
        != "invalid_or_revoked_password"
    ):
        pytest.fail("password failure was misclassified")
    if (
        classify_failure(
            kind="OperationalError",
            phase="query",
            sqlstate="42501",
            excerpt="",
        )
        != "query_permission_failure"
    ):
        pytest.fail("grant failure was misclassified")
    if (
        classify_failure(
            kind="OperationalError",
            phase="connection",
            sqlstate="08006",
            excerpt="",
        )
        != "database_or_pgbouncer_unreachable"
    ):
        pytest.fail("PgBouncer failure was misclassified")
    timeout_class = classify_failure(
        kind="TimeoutError",
        phase="connection",
        sqlstate="",
        excerpt="timed out",
    )
    if timeout_class != "timeout":
        pytest.fail("timeout was misclassified")


def test_discovery_retains_environment_names_but_never_credential_values() -> None:
    """Retain credential source names without retaining credential values."""
    configured_rules = load_settings(ROOT / "domain_checks/config.yaml").rules
    discovered_rules = [rule for rule in configured_rules if rule.rule_id == "discovered-production"]
    if len(discovered_rules) != 1:
        pytest.fail("production catch-all rule was not unique")
    definitions = discover_dependencies(
        InventoryGateway(),
        settings(rules=(discovered_rules[0],)),
        routing={},
    )

    if len(definitions) != 1:
        pytest.fail("discovery did not return exactly one dependency")
    if definitions[0].environment_keys != ("DATABASE_URL",):
        pytest.fail("discovery did not retain the credential source name")
    if "never-retain-me" in repr(definitions):
        pytest.fail("discovery leaked a password")
    if "runtime-user" in repr(definitions):
        pytest.fail("discovery leaked a database login")


def test_nginx_routing_resolution_selects_one_active_slot(tmp_path: Path) -> None:
    """Resolve one exact live blue/green route from Nginx configuration."""
    route_file = tmp_path / "deplanbook.conf"
    _ = route_file.write_text(
        "upstream app { server 127.0.0.1:13141; }\n",
        encoding="utf-8",
    )
    policy = RoutingPolicy(
        policy_id="deplanbook",
        kind="nginx_upstream_file",
        source=str(route_file),
        slots=("legacy", "blue", "green"),
        header_name=None,
        slot_ports=(("legacy", 3140), ("blue", 13140), ("green", 13141)),
    )
    resolution = resolve_routing((policy,), timeout_seconds=1.0)["deplanbook"]

    if resolution.slot_state("green") != ("active", 100):
        pytest.fail("green slot was not active")
    if resolution.slot_state("blue") != ("inactive", 0):
        pytest.fail("blue slot was not inactive")


def test_dashboard_loader_fails_loudly_on_invalid_state_and_retains_latency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject malformed collector state and retain a valid dependency latency."""
    state_path = tmp_path / "database-dependencies.json"
    monkeypatch.setenv("DATABASE_DEPENDENCY_STATE_PATH", str(state_path))
    _ = state_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_database_dashboard(now_ts=500.0)

    probe = definition("web")
    state = cycle(
        [probe],
        [
            observation(
                probe,
                at=400.0,
                ok=True,
                latency_ms=_EXPECTED_SUCCESS_LATENCY_MS,
            ),
        ],
        at=400.0,
    )
    _ = state_path.write_text(json.dumps(state), encoding="utf-8")
    dashboard = load_database_dashboard(now_ts=450.0)
    if dashboard["data_state"] != "live":
        pytest.fail("valid collector state was not live")
    latency = present(
        float_value(
            object_list(dashboard.get("items"))[0].get("last_success_latency_ms"),
        ),
        label="dashboard omitted retained success latency",
    )
    if not math.isclose(
        latency,
        _EXPECTED_SUCCESS_LATENCY_MS,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        pytest.fail(
            f"retained success latency changed: expected {_EXPECTED_SUCCESS_LATENCY_MS!r}, got {latency!r}",
        )


@pytest.mark.asyncio
async def test_evidence_endpoint_rejects_a_spec_host_outside_exact_inventory_domain() -> None:
    """Reject evidence requests whose host is outside the exact inventory domain."""
    with pytest.raises(HTTPException) as error:
        await require_public_endpoint(
            "https://127.0.0.1/private",
            inventory_domain="monitoring.pitchai.net",
        )
    if error.value.status_code != _EXPECTED_REJECTED_STATUS:
        pytest.fail("private endpoint used the wrong status")


@pytest.mark.asyncio
async def test_evidence_response_body_is_bounded_before_sanitization() -> None:
    """Bound the fetched evidence body before it reaches sanitation."""
    response_factory = partial(Response, 503, content=b"x" * 20_000)
    response = response_factory()
    body = await bounded_response_body(response)
    if len(body) != _EXPECTED_EVIDENCE_BYTES:
        pytest.fail("evidence response exceeded its byte boundary")
