# Copyright (c) 2026 PitchAI. All rights reserved.
"""Endpoint proof for the proxy-protected legacy capacity dashboard API."""

from __future__ import annotations

import secrets
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from ._broker_account_test_fixtures import LEAK_MARKER, analytics_state, member, objects, raw_account
from ._dashboard_api_test_runtime import (
    BROKER_URL,
    DASHBOARD_CLIENT,
    OPERATOR_HEADERS,
    REFRESH_HEADERS,
    StaticBrokerSource,
    dashboard_application,
    legacy_settings,
)
from ._timeseries_test_fixtures import check, check_equal
from .source import BrokerStateSource
from .timeseries_types import number_value, require_object

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject

CAPACITY_PATH = "/api/v1/capacity"
REFRESH_PATH = "/api/v1/refresh"
OK, UNAUTHORIZED, FORBIDDEN = int(HTTPStatus.OK), int(HTTPStatus.UNAUTHORIZED), int(HTTPStatus.FORBIDDEN)
ACCOUNT_LABEL = "safe@example.com"
CORRUPT_LEDGER = '{"schema_version":1,"samples":[{"at":"bad","accounts":{}}]}'


def _raw_account() -> JsonObject:
    """Return one fresh, healthy broker account with current analytics.

    Returns:
        A raw account whose internal broker id must stay private.
    """
    now = datetime.now(UTC)
    analytics = analytics_state(
        now,
        lifetime_tokens=1_000,
        buckets=[{"start_date": now.date().isoformat(), "tokens": 100}],
        reset_credits=[],
        available_count=1,
    )
    return raw_account(
        ACCOUNT_LABEL,
        now=now,
        account_id="internal-id",
        five_used=25,
        five_reset=now + timedelta(hours=4),
        weekly_used=10,
        last_probe=now,
        credits={"available_count": 1},
        analytics=analytics,
    )


def test_public_health_and_protected_capacity_api(tmp_path: Path) -> None:
    """Prove health is public and minimal while capacity requires a PitchAI operator."""
    source = StaticBrokerSource([_raw_account()])
    application = dashboard_application(legacy_settings(tmp_path), source)

    with DASHBOARD_CLIENT(application) as client:
        health = client.get("/healthz")
        check_equal(health.status_code, OK, "health status")
        health_fields = set(require_object(health.json(), description="health payload"))
        check_equal(health_fields, {"status", "generated_at", "source_stale"}, "health fields")
        check(ACCOUNT_LABEL not in health.text, "health hides account labels")
        denied = client.get(CAPACITY_PATH)
        check_equal(denied.status_code, UNAUTHORIZED, "anonymous capacity status")
        check_equal(denied.headers["x-robots-tag"], "noindex, nofollow, noarchive", "robots header")
        foreign_identity = client.get(CAPACITY_PATH, headers={"X-PitchAI-Email": "operator@example.com"})
        check_equal(foreign_identity.status_code, UNAUTHORIZED, "foreign identity capacity status")
        response = client.get(CAPACITY_PATH, headers=OPERATOR_HEADERS)
        check_equal(response.status_code, OK, "operator capacity status")
        payload = require_object(response.json(), description="capacity payload")
        check_equal(payload["schema_version"], 4, "capacity schema version")
        check_equal(member(payload, "summary")["configured_accounts"], 1, "configured accounts")
        history = member(payload, "usage_history")
        check_equal(history["point_count"], 168, "hourly history points")
        check_equal(history["accounts_reporting"], 1, "accounts reporting history")
        horizons = objects(member(payload, "runout_forecast")["horizons"], "run-out horizons")
        check_equal(len(horizons), 3, "run-out horizons")
        check_equal(member(payload, "reset_bank")["total_available"], 1, "banked resets")
        check_equal(objects(payload["accounts"], "accounts")[0]["label"], ACCOUNT_LABEL, "account label")
        check("internal-id" not in response.text, "internal broker id stays private")
        check(LEAK_MARKER not in response.text, "broker secrets stay private")
        check_equal(response.headers["cache-control"], "private, no-store", "cache control")
        csp = response.headers["content-security-policy"]
        check(csp.startswith("default-src 'self'"), "content security policy")

    check(source.closed is True, "the broker source is closed at shutdown")


def test_dashboard_page_and_refresh_action_require_operator(tmp_path: Path) -> None:
    """Prove the page normalizes the operator and refresh demands an explicit action header."""
    source = StaticBrokerSource([_raw_account()])
    application = dashboard_application(legacy_settings(tmp_path), source)

    with DASHBOARD_CLIENT(application) as client:
        dashboard = client.get("/", headers={"X-PitchAI-Email": "OPERATOR@PITCHAI.NET"})
        check_equal(dashboard.status_code, OK, "dashboard page status")
        check("operator@pitchai.net" in dashboard.text, "operator email is normalized")
        check("https://auth.pitchai.net/oauth2/sign_out" in dashboard.text, "sign-out link")
        missing_action = client.post(REFRESH_PATH, headers=OPERATOR_HEADERS)
        check_equal(missing_action.status_code, FORBIDDEN, "refresh without action header")
        refresh = client.post(REFRESH_PATH, headers=REFRESH_HEADERS)
        check_equal(refresh.status_code, OK, "refresh status")
        refresh_result = require_object(refresh.json(), description="refresh result")
        check_equal(refresh_result["reason"], "safe_probe_disabled", "refresh reason")

    check(source.closed is True, "the broker source is closed at shutdown")


def test_safe_probe_runs_on_startup_and_manual_probe_is_throttled(tmp_path: Path) -> None:
    """Prove startup runs one analytics probe and an immediate manual probe is throttled."""
    source = StaticBrokerSource([_raw_account()])
    application = dashboard_application(legacy_settings(tmp_path, safe_probe=True), source)

    with DASHBOARD_CLIENT(application) as client:
        check_equal(len(source.analytics_probe_batches), 1, "startup analytics probes")
        check_equal(source.probe_batches, [], "startup safe probes")
        response = client.post(REFRESH_PATH, headers=REFRESH_HEADERS)
        check_equal(response.status_code, OK, "manual refresh status")
        result = require_object(response.json(), description="manual refresh result")
        check_equal(result["reason"], "probe_throttled", "manual refresh reason")
        retry_after = number_value(result["retry_after_seconds"])
        check(retry_after is not None and retry_after > 0, "throttled refresh announces a retry delay")
        check_equal(len(source.analytics_probe_batches), 1, "analytics probes after throttling")
        check_equal(source.probe_batches, [], "safe probes after throttling")


def test_corrupt_sample_history_is_reported_without_hiding_live_capacity(tmp_path: Path) -> None:
    """Prove a corrupt sample ledger is reported while live capacity stays visible."""
    history_file = tmp_path / "usage-samples.json"
    history_file.write_text(CORRUPT_LEDGER, encoding="utf-8")
    settings = replace(legacy_settings(tmp_path), history_file=history_file)
    application = dashboard_application(settings, StaticBrokerSource([_raw_account()]))

    with DASHBOARD_CLIENT(application) as client:
        response = client.get(CAPACITY_PATH, headers=OPERATOR_HEADERS)

    check_equal(response.status_code, OK, "capacity status")
    payload = require_object(response.json(), description="capacity payload")
    check_equal(member(payload, "summary")["usable_now"], 1, "usable accounts now")
    check_equal(member(payload, "source")["history_error"], "ValueError", "history error")
    warnings = objects(payload["warnings"], "warnings")
    history_warning = any(warning["code"] == "history_error" for warning in warnings)
    check(history_warning, "history error warning is raised")


def test_state_source_reads_metadata_and_state_but_never_auth_json(tmp_path: Path) -> None:
    """Prove the broker state source reads metadata and state but never auth.json."""
    account_dir = tmp_path / "accounts" / "account-1"
    account_dir.mkdir(parents=True)
    (account_dir / "metadata.json").write_text(
        '{"account_id":"account-1","label":"safe@example.com","enabled":true}',
        encoding="utf-8",
    )
    (account_dir / "state.json").write_text(
        '{"availability":"available","usage":{"email":"safe@example.com"}}',
        encoding="utf-8",
    )
    (account_dir / "auth.json").write_text(
        '{"access_token":"secret","refresh_token":"secret"}',
        encoding="utf-8",
    )
    source = BrokerStateSource(
        data_dir=tmp_path,
        broker_url=BROKER_URL,
        admin_token=secrets.token_hex(16),
        request_timeout_seconds=2,
    )

    with closing(source):
        accounts = source.read_accounts()

    expected: list[JsonObject] = [
        {
            "metadata": {"account_id": "account-1", "label": ACCOUNT_LABEL, "enabled": True},
            "state": {"availability": "available", "usage": {"email": ACCOUNT_LABEL}},
        },
    ]
    check_equal(accounts, expected, "redacted broker accounts")
