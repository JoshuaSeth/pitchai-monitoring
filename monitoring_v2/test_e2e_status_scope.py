# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for the active, parked and disabled E2E status scope."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
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
from .testing_registry import registry_database
from .testing_runtime import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .dashboard_server import DashboardServer
    from .json_types import JsonInput, JsonObject

_NOW = time.time()
_HTTP_OK = 200
_RUN_AGE_SECONDS = 60.0
_INTERVAL_SECONDS = 300
# Production parks a lane for years and expires a pause by leaving it in the past.
_PARKED_UNTIL_TS = 1_893_456_000.0
_EXPIRED_UNTIL_TS = 1_600_000_000.0
_ACTIVE_FAILING = "scope.active_failing"
_ACTIVE_PASSING = "scope.active_passing"
_RESUMED_PASSING = "scope.resumed_passing"
_PARKED_FAILING = "scope.parked_failing"
_DISABLED_FAILING = "scope.disabled_failing"
_ACTIVE_IDS = [_ACTIVE_FAILING, _ACTIVE_PASSING, _RESUMED_PASSING]
_LEGACY_FAILING_COUNT = 3
_EXPECTED_LABELS = {
    _ACTIVE_FAILING: TEST_STATUS_ACTIVE,
    _ACTIVE_PASSING: TEST_STATUS_ACTIVE,
    _RESUMED_PASSING: TEST_STATUS_ACTIVE,
    _PARKED_FAILING: TEST_STATUS_PARKED,
    _DISABLED_FAILING: TEST_STATUS_DISABLED,
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
    _ACTIVE_FAILING: "failing",
    _ACTIVE_PASSING: "passing",
    _RESUMED_PASSING: "passing",
    _PARKED_FAILING: "parked",
    _DISABLED_FAILING: "disabled",
}
# identifier, enabled, disabled_until_ts, disabled_reason, effective_ok
_SEEDED_TESTS: tuple[tuple[str, int, float | None, str | None, int], ...] = (
    (_ACTIVE_FAILING, 1, None, None, 0),
    (_ACTIVE_PASSING, 1, None, None, 1),
    (_RESUMED_PASSING, 1, _EXPIRED_UNTIL_TS, "pause expired", 1),
    (_PARKED_FAILING, 1, _PARKED_UNTIL_TS, "temporary probe cleanup", 0),
    (_DISABLED_FAILING, 0, None, "retired lane", 0),
)
_TENANT_INSERT = (
    "INSERT INTO tenants (id, name, created_at_ts, updated_at_ts) VALUES ('local', 'Local', 1, 1)"
)
_TEST_INSERT = (
    "INSERT INTO tests (id, tenant_id, name, base_url, enabled, disabled_until_ts, disabled_reason,"
    " interval_seconds, definition_json, created_at_ts, updated_at_ts)"
    " VALUES (?, 'local', ?, 'https://example.invalid/', ?, ?, ?, ?, '{}', 1, 1)"
)
_STATE_INSERT = (
    "INSERT INTO test_state (test_id, effective_ok, fail_streak, success_streak) VALUES (?, ?, 0, 0)"
)
_RUN_INSERT = (
    "INSERT INTO runs (id, test_id, scheduled_for_ts, finished_at_ts, status) VALUES (?, ?, ?, ?, ?)"
)


def _seed_registry(path: Path) -> None:
    """Seed one active failing, active passing, resumed, parked and disabled row."""
    with closing(sqlite3.connect(str(path), timeout=30)) as connection:
        _ = connection.execute(_TENANT_INSERT)
        for identifier, enabled, until_ts, reason, effective_ok in _SEEDED_TESTS:
            _ = connection.execute(
                _TEST_INSERT,
                (identifier, identifier, enabled, until_ts, reason, _INTERVAL_SECONDS),
            )
            _ = connection.execute(_STATE_INSERT, (identifier, effective_ok))
            _ = connection.execute(
                _RUN_INSERT,
                (
                    f"{identifier}.run",
                    identifier,
                    _NOW - _RUN_AGE_SECONDS,
                    _NOW - _RUN_AGE_SECONDS,
                    "fail" if effective_ok == 0 else "pass",
                ),
            )
        connection.commit()


def _registry_settings(root: Path) -> RegistrySettings:
    """Return settings for one fixture database holding the deployed registry schema."""
    path = registry_database(root / "e2e-registry.db")
    _seed_registry(path)
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
        {"test_id": _ACTIVE_FAILING, "enabled": 1, "effective_ok": 0},
        {"test_id": _DISABLED_FAILING, "enabled": 0, "effective_ok": 0},
        {"test_id": _PARKED_FAILING, "enabled": 1, "disabled_until_ts": _PARKED_UNTIL_TS, "effective_ok": 0},
        {"test_id": _RESUMED_PASSING, "enabled": 1, "disabled_until_ts": _EXPIRED_UNTIL_TS, "effective_ok": 0},
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
        _ACTIVE_FAILING: TEST_STATUS_ACTIVE,
        _DISABLED_FAILING: TEST_STATUS_DISABLED,
        _PARKED_FAILING: TEST_STATUS_PARKED,
        _RESUMED_PASSING: TEST_STATUS_ACTIVE,
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
    _seed_registry(tmp_path / "e2e-registry.db")
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
