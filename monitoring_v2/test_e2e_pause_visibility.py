# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for parked and disabled pause visibility."""

from __future__ import annotations

import json
import time
from functools import partial
from typing import TYPE_CHECKING, cast

from httpx import AsyncClient

from .dashboard_server import running_dashboard_server
from .e2e_status_scope_runtime import (
    TEST_STATUS_DISABLED,
    TEST_STATUS_PARKED,
    RegistrySettings,
    active_status_summary,
)
from .journeys import build_journeys
from .json_types import float_value, json_object, object_list, optional_object, text_value
from .testing_registry import (
    SCOPE_DISABLED_FAILING,
    SCOPE_DISABLED_REASON,
    SCOPE_PARKED_FAILING,
    SCOPE_PARKED_REASON,
    SCOPE_PARKED_UNTIL_TS,
    SCOPE_RESUMED_PASSING,
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


def _seed_path(root: Path) -> Path:
    """Return one fixture registry database holding the deployed schema and pause rows."""
    path = registry_database(root / "e2e-registry.db")
    seed_status_scope_registry(path, now=_NOW)
    return path


def _settings(root: Path) -> RegistrySettings:
    """Return settings for one fixture database holding the deployed registry schema."""
    return RegistrySettings(db_path=str(_seed_path(root)))


def _rows_by_id(rows: list[JsonObject]) -> dict[str, JsonObject]:
    """Return every row keyed by its test id."""
    return {text_value(row.get("test_id")): row for row in rows}


def _require_pause_metadata(parked: JsonObject, retired: JsonObject) -> None:
    """Fail unless the parked and retired rows kept their horizon and reasons."""
    if float_value(parked.get("disabled_until_ts")) != SCOPE_PARKED_UNTIL_TS:
        pytest.fail(f"parked row lost its resume horizon: {parked}")
    if text_value(parked.get("disabled_reason")) != SCOPE_PARKED_REASON:
        pytest.fail(f"parked row lost its pause reason: {parked}")
    if text_value(retired.get("disabled_reason")) != SCOPE_DISABLED_REASON:
        pytest.fail(f"disabled row lost its disable reason: {retired}")
    if float_value(retired.get("disabled_until_ts")) is not None:
        pytest.fail(f"disabled row gained a resume horizon: {retired}")


def test_scoped_summary_keeps_pause_reason_and_horizon_visible(tmp_path: Path) -> None:
    """Keep the pause reason and resume horizon on the scoped inventory rows."""
    scoped = active_status_summary(_settings(tmp_path))
    inventory = _rows_by_id(object_list(scoped.get("all_tests")))
    _require_pause_metadata(inventory[SCOPE_PARKED_FAILING], inventory[SCOPE_DISABLED_FAILING])
    active = _rows_by_id(object_list(scoped.get("tests")))
    if SCOPE_PARKED_FAILING in active or SCOPE_DISABLED_FAILING in active:
        pytest.fail(f"parked or disabled row leaked into the active set: {sorted(active)}")
    if SCOPE_RESUMED_PASSING not in active:
        pytest.fail(f"expired pause did not re-enter the active set: {sorted(active)}")


def test_journeys_carry_pause_metadata_for_the_dashboard(tmp_path: Path) -> None:
    """Carry reason, horizon and status class into the dashboard journey items."""
    journeys = build_journeys(
        e2e_status=active_status_summary(_settings(tmp_path)),
        dispatch_runs=[],
        domains=[],
        now_ts=_NOW,
    )
    items = _rows_by_id(object_list(journeys.get("items")))
    if text_value(items[SCOPE_PARKED_FAILING].get("status")) != TEST_STATUS_PARKED:
        pytest.fail(f"parked journey lost its status: {items[SCOPE_PARKED_FAILING]}")
    if text_value(items[SCOPE_DISABLED_FAILING].get("status")) != TEST_STATUS_DISABLED:
        pytest.fail(f"disabled journey lost its status: {items[SCOPE_DISABLED_FAILING]}")
    _require_pause_metadata(items[SCOPE_PARKED_FAILING], items[SCOPE_DISABLED_FAILING])


@pytest.fixture(name="paused_dashboard_server")
def paused_dashboard_server_fixture(tmp_path: Path) -> Iterator[DashboardServer]:
    """Yield one isolated production-shaped registry server holding the pause fixture."""
    _seed_path(tmp_path)
    with running_dashboard_server(tmp_path) as server:
        yield server


@pytest.mark.asyncio
async def test_published_dashboard_exposes_pause_metadata(paused_dashboard_server: DashboardServer) -> None:
    """Publish the pause metadata the registry dashboard renders for parked rows."""
    client_factory = partial(AsyncClient, base_url=paused_dashboard_server.base_url)
    async with client_factory() as client:
        response = await client.get(
            "/api/v1/monitoring/summary",
            headers={"Authorization": f"Bearer {paused_dashboard_server.monitor_token}"},
        )
    if response.status_code != _HTTP_OK:
        pytest.fail(f"/api/v1/monitoring/summary returned {response.status_code}: {response.text}")
    dashboard = json_object(cast("JsonInput", json.loads(response.text)))
    journeys = optional_object(optional_object(dashboard.get("dashboards")).get("journeys"))
    items = _rows_by_id(object_list(journeys.get("items")))
    _require_pause_metadata(items[SCOPE_PARKED_FAILING], items[SCOPE_DISABLED_FAILING])
