# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock dashboard HTTP authentication and snapshot API behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status
from fastapi.testclient import TestClient

from auth_usage_dashboard.app import create_app
from auth_usage_dashboard.source import BrokerStateSource
from domain_checks.testing import verify
from tests.auth_test_contract import required_number
from tests.auth_usage_api_support import (
    FakeSource,
    dashboard_settings,
    raw_account,
    required_array,
    required_array_object,
    required_object,
    response_object,
)

UNUSED_BROKER_BEARER = "not-used"
EXPECTED_CAPACITY_SCHEMA_VERSION = 4
EXPECTED_HISTORY_POINT_COUNT = 168
EXPECTED_RUNOUT_HORIZON_COUNT = 3
EXPECTED_CORRUPT_HISTORY_ERROR = "UsageSampleFormatError"

if TYPE_CHECKING:
    from pathlib import Path


def test_protected_dashboard_api_and_public_health_shape(tmp_path: Path) -> None:
    """Protect operational routes while keeping health output identity-free."""
    source = FakeSource([raw_account()])
    app = create_app(dashboard_settings(tmp_path), source=source)

    with TestClient(app) as client:
        health = client.get("/healthz")
        verify(health.status_code == status.HTTP_200_OK)
        verify(
            set(response_object(health))
            == {
                "status",
                "generated_at",
                "source_stale",
            },
        )
        verify("safe@example.com" not in health.text)

        denied = client.get("/api/v1/capacity")
        verify(denied.status_code == status.HTTP_401_UNAUTHORIZED)
        verify(denied.headers["x-robots-tag"] == "noindex, nofollow, noarchive")

        foreign_identity = client.get(
            "/api/v1/capacity",
            headers={"X-PitchAI-Email": "operator@example.com"},
        )
        verify(foreign_identity.status_code == status.HTTP_401_UNAUTHORIZED)

        response = client.get(
            "/api/v1/capacity",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        verify(response.status_code == status.HTTP_200_OK)
        payload = response_object(response)
        verify(payload["schema_version"] == EXPECTED_CAPACITY_SCHEMA_VERSION)
        verify(required_object(payload, "summary")["configured_accounts"] == 1)
        verify(
            required_object(payload, "usage_history")["point_count"]
            == EXPECTED_HISTORY_POINT_COUNT,
        )
        verify(required_object(payload, "usage_history")["accounts_reporting"] == 1)
        verify(
            len(
                required_array(
                    required_object(payload, "runout_forecast"),
                    "horizons",
                ),
            )
            == EXPECTED_RUNOUT_HORIZON_COUNT,
        )
        verify(required_object(payload, "reset_bank")["total_available"] == 1)
        accounts = required_array(payload, "accounts")
        verify(required_array_object(accounts, 0)["label"] == "safe@example.com")
        verify("internal-id" not in response.text)
        verify(response.headers["cache-control"] == "private, no-store")
        verify(
            response.headers["content-security-policy"].startswith(
                "default-src 'self'",
            ),
        )

        dashboard = client.get(
            "/",
            headers={"X-PitchAI-Email": "OPERATOR@PITCHAI.NET"},
        )
        verify(dashboard.status_code == status.HTTP_200_OK)
        verify("operator@pitchai.net" in dashboard.text)
        verify("https://auth.pitchai.net/oauth2/sign_out" in dashboard.text)

        missing_action = client.post(
            "/api/v1/refresh",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        verify(missing_action.status_code == status.HTTP_403_FORBIDDEN)

        refresh = client.post(
            "/api/v1/refresh",
            headers={
                "X-PitchAI-Email": "operator@pitchai.net",
                "X-Auth-Usage-Action": "refresh",
            },
        )
        verify(refresh.status_code == status.HTTP_200_OK)
        verify(response_object(refresh)["reason"] == "safe_probe_disabled")

    verify(source.closed is True)


def test_safe_probe_runs_on_startup_and_manual_probe_is_throttled(
    tmp_path: Path,
) -> None:
    """Run startup analytics once and throttle an immediate manual probe."""
    source = FakeSource([raw_account()])
    app = create_app(dashboard_settings(tmp_path, safe_probe=True), source=source)

    with TestClient(app) as client:
        verify(source.analytics_probe_count == 1)
        verify(source.probe_count == 0)
        response = client.post(
            "/api/v1/refresh",
            headers={
                "X-PitchAI-Email": "operator@pitchai.net",
                "X-Auth-Usage-Action": "refresh",
            },
        )
        verify(response.status_code == status.HTTP_200_OK)
        refresh_payload = response_object(response)
        verify(refresh_payload["reason"] == "probe_throttled")
        retry_after = required_number(
            refresh_payload["retry_after_seconds"],
            label="refresh retry delay",
        )
        verify(retry_after > 0)
        verify(source.analytics_probe_count == 1)
        verify(source.probe_count == 0)


def test_corrupt_sample_history_is_reported_without_hiding_live_capacity(
    tmp_path: Path,
) -> None:
    """Report corrupt history while retaining the current live snapshot."""
    history_file = tmp_path / "usage-samples.json"
    _ = history_file.write_text(
        '{"schema_version":1,"samples":[{"at":"bad","accounts":{}}]}',
        encoding="utf-8",
    )
    settings = dashboard_settings(tmp_path).with_history_file(history_file)
    app = create_app(settings, source=FakeSource([raw_account()]))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/capacity",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )

    verify(response.status_code == status.HTTP_200_OK)
    payload = response_object(response)
    verify(required_object(payload, "summary")["usable_now"] == 1)
    verify(
        required_object(payload, "source")["history_error"]
        == EXPECTED_CORRUPT_HISTORY_ERROR,
    )
    warnings = required_array(payload, "warnings")
    warning_indexes = range(len(warnings))
    warning_objects = (
        required_array_object(warnings, index) for index in warning_indexes
    )
    warning_codes = (
        warning["code"] for warning in warning_objects
    )
    verify("history_error" in warning_codes)


def test_state_source_reads_metadata_and_state_but_never_auth_json(
    tmp_path: Path,
) -> None:
    """Read broker metadata and state without opening account auth JSON."""
    account_dir = tmp_path / "accounts" / "account-1"
    account_dir.mkdir(parents=True)
    _ = (account_dir / "metadata.json").write_text(
        '{"account_id":"account-1","label":"safe@example.com","enabled":true}',
        encoding="utf-8",
    )
    _ = (account_dir / "state.json").write_text(
        '{"availability":"available","usage":{"email":"safe@example.com"}}',
        encoding="utf-8",
    )
    _ = (account_dir / "auth.json").write_text(
        '{"access_token":"secret","refresh_token":"secret"}',
        encoding="utf-8",
    )
    source = BrokerStateSource(
        data_dir=tmp_path,
        broker_url="http://127.0.0.1:38188",
        admin_token=UNUSED_BROKER_BEARER,
        request_timeout_seconds=2,
    )
    try:
        accounts = source.read_accounts()
    finally:
        source.close()

    verify(
        accounts
        == [
            {
                "metadata": {
                    "account_id": "account-1",
                    "label": "safe@example.com",
                    "enabled": True,
                },
                "state": {
                    "availability": "available",
                    "usage": {"email": "safe@example.com"},
                },
            },
        ],
    )
