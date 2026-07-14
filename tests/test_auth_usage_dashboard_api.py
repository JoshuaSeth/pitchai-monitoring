from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from auth_usage_dashboard.app import create_app
from auth_usage_dashboard.settings import DashboardSettings
from auth_usage_dashboard.source import BrokerStateSource


UTC = timezone.utc


class FakeSource:
    def __init__(self, accounts: list[dict[str, Any]]) -> None:
        self.accounts = accounts
        self.probe_count = 0
        self.analytics_probe_count = 0
        self.closed = False

    def read_accounts(self) -> list[dict[str, Any]]:
        return deepcopy(self.accounts)

    def probe_accounts(self, accounts: list[dict[str, Any]]) -> dict[str, str]:
        self.probe_count += 1
        return {}

    def probe_analytics(self, accounts: list[dict[str, Any]]) -> dict[str, str]:
        self.analytics_probe_count += 1
        return {}

    def close(self) -> None:
        self.closed = True


def _raw_account() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "metadata": {
            "account_id": "internal-id",
            "label": "safe@example.com",
            "enabled": True,
        },
        "state": {
            "availability": "available",
            "last_probe_at": now.isoformat(),
            "usage": {
                "email": "safe@example.com",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 25,
                        "reset_at": (now + timedelta(hours=4)).isoformat(),
                        "limit_window_seconds": 18_000,
                    },
                    "secondary_window": {
                        "used_percent": 10,
                        "reset_at": (now + timedelta(days=6)).isoformat(),
                        "limit_window_seconds": 604_800,
                    },
                },
                "rate_limit_reset_credits": {"available_count": 1},
            },
            "analytics": {
                "last_probe_at": now.isoformat(),
                "token_usage_updated_at": now.isoformat(),
                "token_usage": {
                    "summary": {"lifetime_tokens": 1_000},
                    "daily_usage_buckets": [
                        {"start_date": now.date().isoformat(), "tokens": 100}
                    ],
                },
                "reset_credits_updated_at": now.isoformat(),
                "reset_credits": {"available_count": 1, "credits": []},
                "errors": {},
            },
        },
    }


def _settings(tmp_path: Path, *, safe_probe: bool = False) -> DashboardSettings:
    return DashboardSettings(
        broker_data_dir=tmp_path,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token="test-admin-token",
        safe_probe_enabled=safe_probe,
        probe_on_startup=safe_probe,
        snapshot_refresh_seconds=300,
        safe_probe_interval_seconds=60,
        manual_probe_min_interval_seconds=30,
        stale_after_seconds=600,
        require_proxy_auth=True,
    )


def test_protected_dashboard_api_and_public_health_shape(tmp_path: Path) -> None:
    source = FakeSource([_raw_account()])
    app = create_app(_settings(tmp_path), source=source)

    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert set(health.json()) == {"status", "generated_at", "source_stale"}
        assert "safe@example.com" not in health.text

        denied = client.get("/api/v1/capacity")
        assert denied.status_code == 401
        assert denied.headers["x-robots-tag"] == "noindex, nofollow, noarchive"

        foreign_identity = client.get(
            "/api/v1/capacity",
            headers={"X-PitchAI-Email": "operator@example.com"},
        )
        assert foreign_identity.status_code == 401

        response = client.get(
            "/api/v1/capacity",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == 4
        assert payload["summary"]["configured_accounts"] == 1
        assert payload["usage_history"]["point_count"] == 168
        assert payload["usage_history"]["accounts_reporting"] == 1
        assert len(payload["runout_forecast"]["horizons"]) == 3
        assert payload["reset_bank"]["total_available"] == 1
        assert payload["accounts"][0]["label"] == "safe@example.com"
        assert "internal-id" not in response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["content-security-policy"].startswith(
            "default-src 'self'"
        )

        dashboard = client.get(
            "/",
            headers={"X-PitchAI-Email": "OPERATOR@PITCHAI.NET"},
        )
        assert dashboard.status_code == 200
        assert "operator@pitchai.net" in dashboard.text
        assert "https://auth.pitchai.net/oauth2/sign_out" in dashboard.text

        missing_action = client.post(
            "/api/v1/refresh",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        assert missing_action.status_code == 403

        refresh = client.post(
            "/api/v1/refresh",
            headers={"X-PitchAI-Email": "operator@pitchai.net", "X-Auth-Usage-Action": "refresh"},
        )
        assert refresh.status_code == 200
        assert refresh.json()["reason"] == "safe_probe_disabled"

    assert source.closed is True


def test_safe_probe_runs_on_startup_and_manual_probe_is_throttled(
    tmp_path: Path,
) -> None:
    source = FakeSource([_raw_account()])
    app = create_app(_settings(tmp_path, safe_probe=True), source=source)

    with TestClient(app) as client:
        assert source.analytics_probe_count == 1
        assert source.probe_count == 0
        response = client.post(
            "/api/v1/refresh",
            headers={"X-PitchAI-Email": "operator@pitchai.net", "X-Auth-Usage-Action": "refresh"},
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "probe_throttled"
        assert response.json()["retry_after_seconds"] > 0
        assert source.analytics_probe_count == 1
        assert source.probe_count == 0


def test_corrupt_sample_history_is_reported_without_hiding_live_capacity(
    tmp_path: Path,
) -> None:
    history_file = tmp_path / "usage-samples.json"
    history_file.write_text(
        '{"schema_version":1,"samples":[{"at":"bad","accounts":{}}]}', encoding="utf-8"
    )
    settings = replace(_settings(tmp_path), history_file=history_file)
    app = create_app(settings, source=FakeSource([_raw_account()]))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/capacity", headers={"X-PitchAI-Email": "operator@pitchai.net"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["usable_now"] == 1
    assert payload["source"]["history_error"] == "ValueError"
    assert any(warning["code"] == "history_error" for warning in payload["warnings"])


def test_state_source_reads_metadata_and_state_but_never_auth_json(
    tmp_path: Path,
) -> None:
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
        broker_url="http://127.0.0.1:38188",
        admin_token="not-used",
        request_timeout_seconds=2,
    )
    try:
        accounts = source.read_accounts()
    finally:
        source.close()

    assert accounts == [
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
        }
    ]
