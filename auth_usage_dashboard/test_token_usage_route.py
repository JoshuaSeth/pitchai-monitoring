# Copyright (c) 2026 PitchAI. All rights reserved.
"""Endpoint proof for the protected, cached fleet token ledger route."""

from __future__ import annotations

import io
import json
import os
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from ._scheduling_capacity_test_fixtures import StaticCapacityService, dashboard_settings, operator_snapshot
from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import test_client_factory
from .token_ledger.fleet_store import connect_fleet, ingest
from .token_usage_routes import TOKEN_LEDGER_FILE_ENVIRONMENT_VARIABLE, TOKEN_LEDGER_NODES_ENVIRONMENT_VARIABLE

if TYPE_CHECKING:
    from .service import CapacityService, StateSource
    from .timeseries_types import JsonObject

OPERATOR = {"X-PitchAI-Email": "priority-engine@pitchai.net"}


def _ledger(path: Path, hour: int) -> None:
    connection = connect_fleet(path)
    row = {"hour_epoch": hour, "cell": "c", "project": "dft", "agent": "a", "provider": "openai", "model": "gpt-6-astra", "route": "codex_account", "project_title": "DFT", "input": 90, "cached_input": 40, "output": 10, "reasoning": 0, "total": 100, "requests": 2, "change_seq": 1}
    ingest(connection, "master", io.StringIO(json.dumps({"kind": "header"}) + "\n" + json.dumps(row) + "\n"))
    connection.close()


def test_token_usage_route_requires_identity_and_serves_cached_layers(tmp_path: Path) -> None:
    database = tmp_path / "token-ledger.sqlite3"
    import time  # noqa: PLC0415 - test-local clock

    _ledger(database, int(time.time()) // 3600 * 3600)
    environment = {TOKEN_LEDGER_FILE_ENVIRONMENT_VARIABLE: str(database), TOKEN_LEDGER_NODES_ENVIRONMENT_VARIABLE: "master"}
    with patch.dict(os.environ, environment):
        application = create_scheduling_app(
            dashboard_settings(tmp_path),
            service=cast("CapacityService", cast("object", StaticCapacityService(operator_snapshot()))),
            source=cast("StateSource", object()),
        )
        with test_client_factory(application) as client:
            assert client.get("/api/v1/token-usage").status_code == int(HTTPStatus.UNAUTHORIZED)
            response = client.get("/api/v1/token-usage?span=24h", headers=OPERATOR)
            assert response.status_code == int(HTTPStatus.OK)
            payload = cast("JsonObject", response.json())
            assert payload["range"] == "24h"
            dimensions = cast("JsonObject", payload["dimensions"])
            project = cast("list[JsonObject]", cast("JsonObject", dimensions["project"])["series"])[0]
            assert project["label"] == "DFT"
            assert cast("JsonObject", project["totals"])["fresh"] == 60
            database.unlink()
            cached = client.get("/api/v1/token-usage?span=24h", headers=OPERATOR)
            assert cast("JsonObject", cached.json())["dimensions"] == dimensions
            fallback = cast("JsonObject", client.get("/api/v1/token-usage?span=10y", headers=OPERATOR).json())
            assert fallback["range"] == "7d"
