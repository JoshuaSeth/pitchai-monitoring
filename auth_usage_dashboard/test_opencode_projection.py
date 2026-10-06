# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the OpenCode Go subscription list: statuses, windows, summary and route."""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from ._scheduling_capacity_test_fixtures import StaticCapacityService, dashboard_settings, operator_snapshot
from ._timeseries_test_fixtures import check, check_equal
from .opencode_projection import project_opencode
from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import test_client_factory
from .timeseries_types import optional_object, require_object

if TYPE_CHECKING:
    from pathlib import Path

    from .service import CapacityService, StateSource
    from .timeseries_types import JsonObject, JsonValue

NOW = datetime(2026, 10, 6, 8, 0, tzinfo=UTC).timestamp()
MONTHLY_RESET = "2026-10-22T16:59:26.000Z"
OPERATOR = {"X-PitchAI-Email": "priority-engine@pitchai.net"}
SUBSCRIPTIONS = 4
FULL_PERCENT = 100.0


def _row(label: str, *, monthly: float, cooldown: float | None = None, last_status: int | None = None) -> JsonObject:
    windows: JsonObject = {
        "rolling": {"used_percent": 0.0, "resets_at": "2026-10-06T13:05:40.000Z", "status": "ok"},
        "weekly": {"used_percent": 12.0, "resets_at": "2026-10-12T00:00:00.000Z", "status": "ok"},
        "monthly": {
            "used_percent": monthly,
            "resets_at": MONTHLY_RESET,
            "status": "rate-limited" if monthly >= FULL_PERCENT else "ok",
        },
    }
    return {
        "label": label,
        "windows": windows,
        "auth_valid": last_status not in {401, 403},
        "last_status": last_status,
        "cooldown_until": cooldown,
        "error": None,
    }


def _accounts(payload: JsonObject) -> list[JsonObject]:
    rows = payload.get("accounts")
    return [optional_object(row) for row in rows] if isinstance(rows, list) else []


def test_statuses_follow_windows_bridge_cooldown_and_auth() -> None:
    """Prove limited, cooldown, sign-in and ready subscriptions are told apart."""
    rows: list[JsonValue] = [
        _row("info@pitchai.net", monthly=100.0, cooldown=NOW + 3_600, last_status=429),
        _row("sales@pitchai.net", monthly=40.0, cooldown=NOW + 7_200, last_status=429),
        _row("support@pitchai.net", monthly=10.0, last_status=401),
        _row("onboarding@pitchai.net", monthly=5.0),
    ]
    payload = project_opencode({"generated_at": NOW - 60, "accounts": rows}, now=NOW)
    accounts = _accounts(payload)
    check_equal(
        [account.get("status") for account in accounts],
        ["limited", "cooldown", "auth_invalid", "ready"],
        "statuses in keyring order",
    )
    limited = accounts[0]
    check_equal(limited.get("limited_by"), ["monthly"], "the monthly window is used up")
    check_equal(limited.get("available_at"), "2026-10-22T16:59:26Z", "usable again at the monthly reset")
    monthly = optional_object(optional_object(limited.get("windows")).get("monthly"))
    check_equal((monthly.get("remaining_percent"), monthly.get("reported")), (0.0, True), "Codex window shape")
    weekly = optional_object(optional_object(accounts[3].get("windows")).get("weekly"))
    check_equal(weekly.get("window_seconds"), 604_800, "weekly window length")
    check_equal(accounts[3].get("available_at"), None, "a ready subscription needs no wait")
    summary = optional_object(payload.get("summary"))
    check_equal((summary.get("subscriptions"), summary.get("ready")), (SUBSCRIPTIONS, 1), "pool counts")
    check_equal(summary.get("next_available_at"), "2026-10-06T10:00:00Z", "earliest moment a key frees up")
    check(payload.get("stale") is False, "a minute-old export is fresh")


def test_missing_export_is_explicitly_unavailable() -> None:
    """Prove a missing exporter snapshot is reported, never shown as an empty healthy pool."""
    payload = project_opencode(None, now=NOW)
    check(payload.get("stale") is True and payload.get("error") is not None, "unavailable is explicit")
    check_equal(_accounts(payload), [], "no invented subscriptions")


def test_route_requires_identity_and_answers(tmp_path: Path) -> None:
    """Prove the subscription list is SSO-protected and always answers with the contract."""
    application = create_scheduling_app(
        dashboard_settings(tmp_path),
        service=cast("CapacityService", cast("object", StaticCapacityService(operator_snapshot()))),
        source=cast("StateSource", object()),
    )
    with test_client_factory(application) as client:
        denied = client.get("/api/v1/opencode-accounts")
        check_equal(denied.status_code, int(HTTPStatus.UNAUTHORIZED), "identity required")
        response = client.get("/api/v1/opencode-accounts", headers=OPERATOR)
        check_equal(response.status_code, int(HTTPStatus.OK), "operators get the list")
        payload = require_object(response.json(), description="opencode payload")
        check_equal(payload.get("schema_version"), 1, "schema version")
