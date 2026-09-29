# Copyright (c) 2026 PitchAI. All rights reserved.
"""Unit and endpoint proof for the redacted Claude account inventory."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final
from unittest.mock import patch

from ._scheduling_capacity_test_fixtures import (
    StaticCapacityService,
    dashboard_settings,
    operator_snapshot,
)
from ._timeseries_test_fixtures import UsageTimeSeriesCase, check, check_equal
from .claude_accounts import auth_status, collect
from .claude_routes import CLAUDE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE, read_snapshot
from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import test_client_factory

if TYPE_CHECKING:
    from pathlib import Path

    from .scheduling_web_runtime import Application
    from .service import CapacityService, StateSource
    from .timeseries_types import JsonObject

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC).timestamp()
STALE_GAP_SECONDS, OLD_OBSERVED_GAP_SECONDS = 200.0, 1_000.0
FRESH_OBSERVED_GAP_SECONDS, RESET_GAP_SECONDS = 30.0, 3_600.0
PRIMARY_UTILIZATION = 0.76
PRIMARY_USED_PERCENT = 76.0
OWNER_ROOT_NAME, OWNER_DIRECTORY_NAME = "claude-owners", "test-owner"
OPERATOR_HEADERS = {"X-PitchAI-Email": "priority-engine@pitchai.net"}
FOREIGN_HEADERS = {"X-PitchAI-Email": "operator@example.com"}
UNAVAILABLE, LEAK = "Claude account status is unavailable", "must-not-leak"
EXPECTED_FRESH, EXPECTED_STALE, EXPECTED_ROTATION = False, True, True
FAKE_CLI_SCRIPT = """#!/bin/sh
printf '%s' "${ANTHROPIC_API_KEY:-unset}" > env.txt
printf '{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty",'\\
'"subscriptionType": "max", "email": "%s@pitchai.net", "apiKeySource": null, "accessToken": "secret-%s"}\\n' \\
"$(basename "$PWD")" "${ANTHROPIC_API_KEY:-unset}"
"""


def curated_snapshot() -> JsonObject:
    """Return one fresh curated snapshot the endpoint must serve redacted."""
    moment = time.time()
    return {
        "schema_version": 1,
        "generated_at": moment,
        "accounts": [
            {
                "email": "person@pitchai.net",
                "plan": "max",
                "role": "Primary",
                "signed_in": True,
                "status": "ready",
                "rotation_enabled": True,
                "used_percent": PRIMARY_USED_PERCENT,
                "window": "seven_day",
                "owner_observed_at": moment,
                "usage_observed_at": moment,
                "refresh_token": LEAK,
            },
        ],
    }


@final
class ClaudeAccountsTest(UsageTimeSeriesCase):
    """Prove the Claude inventory stays redacted, explicit, and fail-closed."""

    def fake_cli(self) -> Path:
        """Return the path of one deterministic stand-in for the official CLI."""
        path = self.root / "claude"
        path.write_text(FAKE_CLI_SCRIPT, encoding="utf-8")
        path.chmod(0o755)
        return path

    def write_owner(
        self,
        *,
        written_at: float,
        user_id: str = "person",
        configuration_user_id: str | None = None,
        primary_home: str = "home",
    ) -> Path:
        """Return the path of one written owner directory with two profiles."""
        state = self.root / OWNER_ROOT_NAME / OWNER_DIRECTORY_NAME
        (state / "home").mkdir(parents=True, exist_ok=True)
        (state / "secondary").mkdir(exist_ok=True)
        principal = {"provider": "claude_code", "tenant_id": "tenant", "user_id": user_id}
        (state / "owner.json").write_text(json.dumps(principal), encoding="utf-8")
        profiles = [{"id": "primary", "home": primary_home}, {"id": "secondary", "home": "secondary"}]
        configuration = {**principal, "user_id": configuration_user_id or user_id, "accounts": profiles}
        (state / "accounts.json").write_text(json.dumps(configuration), encoding="utf-8")
        health = {
            "writtenAt": written_at,
            "accounts": [
                {
                    "id": "primary",
                    "usageLimit": {
                        "limitType": "seven_day",
                        "utilization": PRIMARY_UTILIZATION,
                        "observedAt": written_at - OLD_OBSERVED_GAP_SECONDS,
                        "limitedUntil": written_at + RESET_GAP_SECONDS,
                    },
                },
                {
                    "id": "secondary",
                    "usageLimit": {
                        "limitType": "five_hour",
                        "utilization": None,
                        "observedAt": written_at - FRESH_OBSERVED_GAP_SECONDS,
                        "limitedUntil": None,
                    },
                },
            ],
        }
        (state / "health.json").write_text(json.dumps(health), encoding="utf-8")
        return state

    def write_snapshot(self, document: JsonObject, name: str = "claude-accounts.json") -> Path:
        """Return the path of one written snapshot document inside the test root."""
        target = self.root / name
        target.write_text(json.dumps(document), encoding="utf-8")
        return target

    def create_application(self, service: StaticCapacityService) -> Application:
        """Return the protected dashboard composed around one static capacity service."""
        return create_scheduling_app(
            dashboard_settings(self.root),
            service=cast("CapacityService", cast("object", service)),
            source=cast("StateSource", object()),
        )

    def test_collect_reports_identity_usage_and_unreported_limits(self) -> None:
        """Collect both profiles and keep unreported usage explicitly unknown."""
        state = self.write_owner(written_at=NOW)
        raw = collect(state.parent, self.fake_cli(), now=NOW)
        check_equal(raw["errors"], [], "inventory error signal")
        check("secret-" not in json.dumps(raw), "credential leaked into the export")
        path = self.write_snapshot(raw)

        snapshot = read_snapshot(path, now=NOW)
        check_equal(snapshot["schema_version"], 1, "schema version")
        check_equal(snapshot["stale"], EXPECTED_FRESH, "fresh snapshot")
        check_equal(snapshot["error"], None, "snapshot error signal")
        rows = cast("list[JsonObject]", snapshot["accounts"])
        check_equal(len(rows), 2, "account count")
        primary, secondary = rows
        expected_reset = datetime.fromtimestamp(NOW + RESET_GAP_SECONDS, UTC).isoformat()
        check_equal(primary["email"], "home@pitchai.net", "primary identity")
        check_equal(primary["role"], "Primary", "primary role")
        check_equal(primary["status"], "cooldown", "primary status")
        check_equal(primary["used_percent"], PRIMARY_USED_PERCENT, "primary usage")
        check_equal(primary["window"], "seven_day", "primary usage window")
        check_equal(primary["usage_stale"], EXPECTED_STALE, "old reading flagged stale")
        check_equal(primary["cooldown_until"], expected_reset, "primary reset moment")
        check_equal(secondary["email"], "secondary@pitchai.net", "fallback identity")
        check_equal(secondary["role"], "Fallback", "fallback role")
        check_equal(secondary["status"], "ready", "fallback status")
        check_equal(secondary["used_percent"], None, "unreported usage stays unknown")
        check_equal(secondary["window"], "five_hour", "fallback usage window")
        check_equal(secondary["usage_stale"], EXPECTED_FRESH, "fresh reading kept")
        check_equal(secondary["rotation_enabled"], EXPECTED_ROTATION, "rotation flag")

        expired = read_snapshot(path, now=NOW + STALE_GAP_SECONDS)
        check_equal(expired["stale"], EXPECTED_STALE, "expired snapshot")
        expired_rows = cast("list[JsonObject]", expired["accounts"])
        expired_statuses = [row["status"] for row in expired_rows]
        check_equal(expired_statuses, ["unavailable", "unavailable"], "stale rows stay unavailable")

    def test_collect_rejects_foreign_principal_and_profile_escape(self) -> None:
        """Reject mismatched principals and homes outside the owner directory."""
        cli = self.fake_cli()
        foreign = self.write_owner(written_at=NOW, configuration_user_id="other")
        foreign_result = collect(foreign.parent, cli, now=NOW)
        escaped = self.write_owner(written_at=NOW, primary_home="/root")
        escaped_result = collect(escaped.parent, cli, now=NOW)
        check_equal(foreign_result["accounts"], [], "foreign principal accounts")
        check_equal(foreign_result["errors"], ["owner_inventory_unavailable"], "foreign principal error")
        check_equal(escaped_result["accounts"], [], "escaped profile accounts")
        check_equal(escaped_result["errors"], ["owner_inventory_unavailable"], "escaped profile error")

    def test_auth_status_uses_the_official_cli_and_scrubs_the_environment(self) -> None:
        """Run the status command without leaking process credentials to it."""
        cli = self.fake_cli()
        home = self.root / "home"
        home.mkdir()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": LEAK}):
            identity = auth_status(cli, home)
        environment_marker = (home / "env.txt").read_text(encoding="utf-8")
        expected = {"signed_in": True, "email": "home@pitchai.net", "plan": "max"}
        check_equal(identity, expected, "identity summary")
        check_equal(environment_marker, "unset", "scrubbed command environment")

    def test_endpoint_requires_pitchai_identity_and_serves_redacted_rows(self) -> None:
        """Require one PitchAI operator identity and serve only collected facts."""
        path = self.write_snapshot(curated_snapshot())
        service = StaticCapacityService(operator_snapshot())
        environment = {CLAUDE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE: str(path)}
        with patch.dict(os.environ, environment), test_client_factory(
            self.create_application(service),
        ) as client:
            denied = client.get("/api/v1/claude-accounts")
            foreign = client.get("/api/v1/claude-accounts", headers=FOREIGN_HEADERS)
            response = client.get("/api/v1/claude-accounts", headers=OPERATOR_HEADERS)
            check_equal(denied.status_code, int(HTTPStatus.UNAUTHORIZED), "missing identity")
            check_equal(foreign.status_code, int(HTTPStatus.UNAUTHORIZED), "foreign identity")
            check_equal(response.status_code, int(HTTPStatus.OK), "endpoint status")
            payload = cast("JsonObject", response.json())
            rows = cast("list[JsonObject]", payload["accounts"])
            check_equal(payload["stale"], EXPECTED_FRESH, "endpoint freshness")
            check_equal(len(rows), 1, "endpoint account count")
            check_equal(rows[0]["email"], "person@pitchai.net", "endpoint identity")
            check(LEAK not in response.text, "unexpected field escaped the endpoint")

    def test_endpoint_reports_unavailable_when_the_source_is_absent(self) -> None:
        """Keep a missing deployment source explicit instead of serving stale rows."""
        service = StaticCapacityService(operator_snapshot())
        missing = self.root / "absent-deployment.json"
        environment = {CLAUDE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE: str(missing)}
        with patch.dict(os.environ, environment), test_client_factory(
            self.create_application(service),
        ) as client:
            response = client.get("/api/v1/claude-accounts", headers=OPERATOR_HEADERS)
            check_equal(response.status_code, int(HTTPStatus.OK), "availability status")
            payload = cast("JsonObject", response.json())
            check_equal(payload["accounts"], [], "unavailable accounts")
            check_equal(payload["error"], UNAVAILABLE, "unavailable error")
            check_equal(payload["stale"], EXPECTED_STALE, "unavailable staleness")
