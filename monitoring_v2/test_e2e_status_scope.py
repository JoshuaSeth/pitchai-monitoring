# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for the active, parked and disabled E2E status scope."""

from __future__ import annotations

import json
import time
from functools import partial
from typing import TYPE_CHECKING, cast

from httpx import AsyncClient

from .dashboard_server import running_dashboard_server
from .e2e_status_scope_runtime import (
    FAILING_SCOPE_ACTIVE,
    TEST_STATUS_ACTIVE,
    TEST_STATUS_DISABLED,
    TEST_STATUS_PARKED,
    E2EStatusCounts,
    RegistrySettings,
    active_status_summary,
    count_test_statuses,
    unscoped_status_summary,
)
from .journeys import build_journeys
from .json_types import json_object, object_list, optional_object, text_value
from .testing_registry import (
    SCOPE_ACTIVE_FAILING,
    SCOPE_ACTIVE_PASSING,
    SCOPE_DISABLED_FAILING,
    SCOPE_EXPIRED_UNTIL_TS,
    SCOPE_PARKED_FAILING,
    SCOPE_PARKED_UNTIL_TS,
    SCOPE_RESUMED_PASSING,
    SCOPE_TENANT_TOKEN,
    registry_database,
    seed_status_scope_registry,
)
from .testing_runtime import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .dashboard_server import DashboardServer
    from .json_types import JsonInput, JsonObject

_NOW = time.time()
_HTTP_OK = 200
_ACTIVE_IDS = [SCOPE_ACTIVE_FAILING, SCOPE_ACTIVE_PASSING, SCOPE_RESUMED_PASSING]
_LEGACY_FAILING_COUNT = 3
_EXPECTED_LABELS = {
    SCOPE_ACTIVE_FAILING: TEST_STATUS_ACTIVE,
    SCOPE_ACTIVE_PASSING: TEST_STATUS_ACTIVE,
    SCOPE_RESUMED_PASSING: TEST_STATUS_ACTIVE,
    SCOPE_PARKED_FAILING: TEST_STATUS_PARKED,
    SCOPE_DISABLED_FAILING: TEST_STATUS_DISABLED,
}
_EXPECTED_STATUS_COUNTS = {
    "total_tests": 3,
    "enabled_tests": 4,
    "active_tests": 3,
    "passing_tests": 2,
    "failing_tests": 1,
    "parked_tests": 1,
    "parked_failing_tests": 1,
    "disabled_tests": 1,
    "disabled_failing_tests": 1,
}
_EXPECTED_JOURNEY_COUNTS = {
    "total": 3,
    "active": 3,
    "passing": 2,
    "failing": 1,
    "parked": 1,
    "disabled": 1,
}
_EXPECTED_JOURNEY_STATUS = {
    SCOPE_ACTIVE_FAILING: "failing",
    SCOPE_ACTIVE_PASSING: "passing",
    SCOPE_RESUMED_PASSING: "passing",
    SCOPE_PARKED_FAILING: "parked",
    SCOPE_DISABLED_FAILING: "disabled",
}


def _registry_settings(root: Path) -> RegistrySettings:
    """Return settings for one fixture database holding the deployed registry schema."""
    path = registry_database(root / "e2e-registry.db")
    seed_status_scope_registry(path, now=_NOW)
    return RegistrySettings(db_path=str(path))


def _labels(rows: list[JsonObject], key: str) -> dict[str, str]:
    """Return one text column of every row keyed by test id."""
    labels: dict[str, str] = {}
    for row in rows:
        labels[text_value(row.get("test_id"))] = text_value(row.get(key))
    return labels


async def _get_json(client: AsyncClient, path: str, token: str) -> JsonObject:
    """Return one protected monitoring document over local HTTP."""
    response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
    if response.status_code != _HTTP_OK:
        pytest.fail(f"{path} returned {response.status_code}: {response.text}")
    return json_object(cast("JsonInput", json.loads(response.text)))


def test_status_classes_separate_schedulable_parked_and_disabled_rows() -> None:
    """Keep an enabled failure alertable while parked and retired rows stay out."""
    rows: list[JsonObject] = [
        {"test_id": SCOPE_ACTIVE_FAILING, "enabled": 1, "effective_ok": 0},
        {"test_id": SCOPE_DISABLED_FAILING, "enabled": 0, "effective_ok": 0},
        {"test_id": SCOPE_PARKED_FAILING, "enabled": 1, "disabled_until_ts": SCOPE_PARKED_UNTIL_TS, "effective_ok": 0},
        {
            "test_id": SCOPE_RESUMED_PASSING,
            "enabled": 1,
            "disabled_until_ts": SCOPE_EXPIRED_UNTIL_TS,
            "effective_ok": 0,
        },
    ]
    counts = count_test_statuses(rows, now_ts=_NOW)
    expected = E2EStatusCounts(
        active=2,
        passing=0,
        failing=2,
        parked=1,
        parked_failing=1,
        disabled=1,
        disabled_failing=1,
    )
    if counts != expected:
        pytest.fail(f"unexpected E2E status counts: {counts}")
    expected_classes = {
        SCOPE_ACTIVE_FAILING: TEST_STATUS_ACTIVE,
        SCOPE_DISABLED_FAILING: TEST_STATUS_DISABLED,
        SCOPE_PARKED_FAILING: TEST_STATUS_PARKED,
        SCOPE_RESUMED_PASSING: TEST_STATUS_ACTIVE,
    }
    if _labels(rows, "status_class") != expected_classes:
        pytest.fail(f"unexpected E2E status classes: {rows}")


def test_scoped_summary_reports_only_active_failures(tmp_path: Path) -> None:
    """Drop parked and disabled history from the failing scope without hiding it."""
    settings = _registry_settings(tmp_path)
    legacy = unscoped_status_summary(settings)
    scoped = active_status_summary(settings)
    if legacy.get("failing_tests") != _LEGACY_FAILING_COUNT:
        pytest.fail(f"legacy status query stopped counting historical failures: {legacy}")
    observed = {key: scoped.get(key) for key in _EXPECTED_STATUS_COUNTS}
    if observed != _EXPECTED_STATUS_COUNTS:
        pytest.fail(f"scoped status counts changed: {observed}")
    if scoped.get("failing_tests_scope") != FAILING_SCOPE_ACTIVE:
        pytest.fail(f"scoped status lost its failing scope: {scoped.get('failing_tests_scope')}")
    if sorted(_labels(object_list(scoped.get("tests")), "test_id")) != _ACTIVE_IDS:
        pytest.fail(f"scoped status exposed non-active rows: {scoped.get('tests')}")
    if _labels(object_list(scoped.get("all_tests")), "status_class") != _EXPECTED_LABELS:
        pytest.fail(f"scoped inventory lost parked or disabled labels: {scoped.get('all_tests')}")


def test_journeys_expose_parked_and_disabled_history_apart_from_active_failures(tmp_path: Path) -> None:
    """Keep the journeys tab showing the active failure plus labelled history."""
    settings = _registry_settings(tmp_path)
    journeys = build_journeys(
        e2e_status=active_status_summary(settings),
        dispatch_runs=[],
        domains=[],
        now_ts=_NOW,
    )
    observed = {key: journeys.get(key) for key in _EXPECTED_JOURNEY_COUNTS}
    if observed != _EXPECTED_JOURNEY_COUNTS:
        pytest.fail(f"journey counts changed: {observed}")
    if _labels(object_list(journeys.get("items")), "status") != _EXPECTED_JOURNEY_STATUS:
        pytest.fail(f"journey rows lost their status classes: {journeys.get('items')}")


@pytest.fixture(name="dashboard_server")
def dashboard_server_fixture(tmp_path: Path) -> Iterator[DashboardServer]:
    """Yield one isolated production-shaped registry server."""
    with running_dashboard_server(tmp_path) as server:
        yield server


@pytest.mark.asyncio
async def test_registry_status_route_publishes_the_scoped_summary(
    tmp_path: Path,
    dashboard_server: DashboardServer,
) -> None:
    """Publish the scoped summary from the status query production installs."""
    seed_status_scope_registry(tmp_path / "e2e-registry.db", now=_NOW)
    client_factory = partial(AsyncClient, base_url=dashboard_server.base_url)
    async with client_factory() as client:
        status = await _get_json(client, "/api/v1/status/summary", dashboard_server.monitor_token)
        dashboard = await _get_json(client, "/api/v1/monitoring/summary", dashboard_server.monitor_token)
    observed = {key: status.get(key) for key in _EXPECTED_STATUS_COUNTS}
    if observed != _EXPECTED_STATUS_COUNTS:
        pytest.fail(f"published status counts changed: {observed}")
    if status.get("failing_tests_scope") != FAILING_SCOPE_ACTIVE:
        pytest.fail(f"published status lost its failing scope: {status.get('failing_tests_scope')}")
    journeys = optional_object(optional_object(dashboard.get("dashboards")).get("journeys"))
    published = {key: journeys.get(key) for key in _EXPECTED_JOURNEY_COUNTS}
    if published != _EXPECTED_JOURNEY_COUNTS:
        pytest.fail(f"dashboard journey counts changed: {published}")
    compatibility = optional_object(dashboard.get("e2e"))
    if compatibility.get("failing_tests") != 1 or compatibility.get("parked_tests") != 1:
        pytest.fail(f"dashboard E2E compatibility block changed: {compatibility}")


@pytest.mark.asyncio
async def test_tenant_status_route_reports_only_active_failures(
    tmp_path: Path,
    dashboard_server: DashboardServer,
) -> None:
    """Keep a tenant's parked and retired rows out of its failing count."""
    seed_status_scope_registry(tmp_path / "e2e-registry.db", now=_NOW)
    legacy = unscoped_status_summary(RegistrySettings(db_path=str(tmp_path / "e2e-registry.db")))
    client_factory = partial(AsyncClient, base_url=dashboard_server.base_url)
    async with client_factory() as client:
        tenant = await _get_json(client, "/api/v1/status/summary", SCOPE_TENANT_TOKEN)
    if legacy.get("failing_tests") != _LEGACY_FAILING_COUNT:
        pytest.fail(f"legacy tenant scope stopped counting historical failures: {legacy}")
    expected_total = _EXPECTED_STATUS_COUNTS["total_tests"]
    expected_failing = _EXPECTED_STATUS_COUNTS["failing_tests"]
    if tenant.get("total_tests") != expected_total or tenant.get("failing_tests") != expected_failing:
        pytest.fail(f"tenant status counts changed: {tenant}")
    if sorted(_labels(object_list(tenant.get("tests")), "test_id")) != _ACTIVE_IDS:
        pytest.fail(f"tenant status exposed non-active rows: {tenant.get('tests')}")
