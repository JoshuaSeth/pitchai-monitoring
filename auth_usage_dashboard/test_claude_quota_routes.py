# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof that the Claude accounts route serves only validated plan-limit readings."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final
from unittest.mock import patch

from ._claude_quota_test_fixtures import FABLE_RESET, LIMITS_TEXT, NOW, SESSION_RESET, ClaudeQuotaCase, usage_reply
from ._scheduling_capacity_test_fixtures import StaticCapacityService, dashboard_settings, operator_snapshot
from ._timeseries_test_fixtures import check, check_equal, require_array
from .claude_routes import CLAUDE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE, read_snapshot
from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import test_client_factory

if TYPE_CHECKING:
    from .service import CapacityService, StateSource
    from .timeseries_types import JsonObject, JsonValue

LEAK = "must-not-leak"
STALE_QUOTA_GAP_SECONDS, FRESH_QUOTA_GAP_SECONDS = 1_000.0, 60.0
OPERATOR_HEADERS = {"X-PitchAI-Email": "priority-engine@pitchai.net"}


def iso(epoch: float) -> str:
    """Return the route's ISO form of one epoch."""
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def stored_row(**quota: JsonValue) -> JsonObject:
    """Return one exported account row with the given quota fields."""
    row: JsonObject = {
        "id": "0123456789abcdef",
        "email": "person@pitchai.net",
        "plan": "max",
        "role": "Primary",
        "signed_in": True,
        "status": "ready",
        "rotation_enabled": True,
        "owner_observed_at": NOW,
        "refresh_token": LEAK,
    }
    return {**row, **quota}


@final
class ClaudeQuotaRouteTest(ClaudeQuotaCase):
    """Prove the route passes validated windows, flags stale readings, and redacts everything else."""

    def public_rows(self, rows: list[JsonValue], *, now: float = NOW) -> list[JsonObject]:
        """Return the public rows the route serves for one stored snapshot."""
        path = self.root / "claude-accounts.json"
        document: JsonObject = {"schema_version": 1, "generated_at": NOW, "accounts": rows, "errors": []}
        path.write_text(json.dumps(document), encoding="utf-8")
        snapshot = read_snapshot(path, now=now)
        check(LEAK not in json.dumps(snapshot), "unexpected field escaped the route")
        return [cast("JsonObject", row) for row in require_array(snapshot["accounts"], "accounts")]

    def test_route_serves_remaining_percent_iso_resets_and_freshness(self) -> None:
        """Serve each window with remaining percent and ISO reset, and flag readings older than 15 minutes."""
        windows: JsonObject = {
            "five_hour": {"used_percent": 34.0, "resets_at": SESSION_RESET},
            "seven_day": {"used_percent": 100.0, "resets_at": None},
        }
        scoped: list[JsonValue] = [{"label": "Fable", "used_percent": 0.0, "resets_at": FABLE_RESET}]
        row = stored_row(
            windows=windows,
            scoped_windows=scoped,
            quota_observed_at=NOW - FRESH_QUOTA_GAP_SECONDS,
            quota_error="probe_timeout",
        )
        (public,) = self.public_rows([row])
        expected: JsonObject = {
            "five_hour": {"used_percent": 34.0, "remaining_percent": 66.0, "resets_at": iso(SESSION_RESET)},
            "seven_day": {"used_percent": 100.0, "remaining_percent": 0.0, "resets_at": None},
        }
        check_equal(public["windows"], expected, "public windows")
        fable: JsonObject = {"label": "Fable", "used_percent": 0.0, "remaining_percent": 100.0}
        check_equal(public["scoped_windows"], [{**fable, "resets_at": iso(FABLE_RESET)}], "public scoped windows")
        check_equal(public["quota_observed_at"], iso(NOW - FRESH_QUOTA_GAP_SECONDS), "reading moment")
        check_equal((public["quota_stale"], public["quota_error"]), (False, "probe_timeout"), "fresh reading")
        (later,) = self.public_rows([row], now=NOW + STALE_QUOTA_GAP_SECONDS)
        check(later["quota_stale"] is True, "old reading was not flagged stale")
        (bare,) = self.public_rows([stored_row()])
        check_equal((bare["windows"], bare["scoped_windows"]), ({}, []), "absent reading")
        check_equal((bare["quota_observed_at"], bare["quota_stale"]), (None, True), "absent reading is stale")

    def test_route_drops_invalid_numbers_unknown_keys_and_codes(self) -> None:
        """Reject non-finite and out-of-range values, unknown windows, long labels and unlisted error codes."""
        windows: JsonObject = {
            "five_hour": {"used_percent": 150.0, "resets_at": SESSION_RESET},
            "seven_day": {"used_percent": float("nan")},
            "seven_day_sonnet": {"used_percent": 5, "resets_at": float("inf"), "refresh_token": LEAK},
            "seven_day_opus": {"used_percent": 3.0},
            LEAK: {"used_percent": 1.0},
        }
        scoped: list[JsonValue] = [
            {"label": "x" * 41, "used_percent": 1.0},
            {"label": "Fable", "used_percent": "5"},
            {"label": "Line\nbreak", "used_percent": 5.0},
            {"label": "Haiku", "used_percent": 2.0, "resets_at": -5, "access_token": LEAK},
        ]
        scoped.extend({"label": f"Model {index}", "used_percent": 1.0} for index in range(5))
        row = stored_row(windows=windows, scoped_windows=scoped, quota_observed_at="recently", quota_error=LEAK)
        (public,) = self.public_rows([row])
        sonnet: JsonObject = {"used_percent": 5.0, "remaining_percent": 95.0, "resets_at": None}
        check_equal(public["windows"], {"seven_day_sonnet": sonnet}, "validated windows")
        served = require_array(public["scoped_windows"], "scoped")
        labels = [cast("JsonObject", item)["label"] for item in served]
        check_equal(labels, ["Haiku", "Model 0", "Model 1"], "validated scoped windows within the cap")
        check_equal((public["quota_observed_at"], public["quota_stale"]), (None, True), "invalid reading moment")
        check_equal(public["quota_error"], None, "unlisted error code")

    def test_collected_readings_reach_the_endpoint(self) -> None:
        """Serve the exporter's readings through the protected endpoint without other fields."""
        for profile in ("primary", "secondary"):
            self.reply(profile, usage_reply(LIMITS_TEXT))
        document = {"schema_version": 1, "generated_at": NOW, "accounts": self.collect_rows(self.settings())}
        path = self.root / "collected.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        application = create_scheduling_app(
            dashboard_settings(self.root),
            service=cast("CapacityService", cast("object", StaticCapacityService(operator_snapshot()))),
            source=cast("StateSource", object()),
        )
        environment = {CLAUDE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE: str(path)}
        with patch.dict(os.environ, environment), test_client_factory(application) as client:
            response = client.get("/api/v1/claude-accounts", headers=OPERATOR_HEADERS)
        check_equal(response.status_code, int(HTTPStatus.OK), "endpoint status")
        rows = require_array(cast("JsonObject", response.json())["accounts"], "accounts")
        primary = cast("JsonObject", rows[0])
        windows = cast("JsonObject", primary["windows"])
        check_equal(sorted(windows), ["five_hour", "seven_day"], "served windows")
        check_equal(cast("JsonObject", windows["five_hour"])["remaining_percent"], 66.0, "served remaining")
        served = require_array(primary["scoped_windows"], "scoped")
        scoped = [cast("JsonObject", item)["label"] for item in served]
        check_equal(scoped, ["Fable"], "served model-scoped windows")
        check("quota_attempted_at" not in response.text, "internal probe bookkeeping escaped")
        check("quota_source" not in response.text, "internal source label escaped")
