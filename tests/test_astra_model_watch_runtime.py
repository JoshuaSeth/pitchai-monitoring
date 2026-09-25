# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runtime scheduling and private-alert tests for the ASTRA watch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from astra_model_watch.audit import AlertState, AuditLog
from astra_model_watch.catalog import CatalogClient
from astra_model_watch.json_types import JsonObject
from astra_model_watch.schedule import WatchRuntime
from astra_model_watch.types import WatchConfig
from astra_model_watch.watch import AstraModelWatch
from astra_model_watch.watch_runtime import WatchDependencies
from tests.astra_watch_support import (
    RecordingNotifier,
    RecordingTransport,
    events,
    jwt_for,
    make_account,
    private_paths,
    temporary_path,
)


def test_production_launcher_uses_astra_capable_catalog_version() -> None:
    """Keep production above the client version that first catalogs ASTRA."""
    launcher = Path(__file__).parents[1] / "ops" / "run_astra_model_watch.sh"

    assert 'readonly CLIENT_VERSION="0.153.1"' in launcher.read_text()


def test_disabled_and_rate_limited_accounts_are_still_checked_independently() -> None:
    """Check every directory-backed account regardless of broker scheduling state."""
    with temporary_path() as root:
        accounts_dir, log_path, state_path = private_paths(root)
        make_account(accounts_dir, "acc-a", "Enabled", enabled=True, token="access-a")
        make_account(accounts_dir, "acc-b", "Disabled", enabled=False, token="access-b")
        _ = (accounts_dir / "acc-b" / "state.json").write_text(
            json.dumps({"availability": "rate_limited"}),
        )
        transport = RecordingTransport({"models": [{"slug": "gpt-normal"}]})
        watch = AstraModelWatch(
            config=WatchConfig(
                accounts_dir=accounts_dir,
                client_version="0.137.0",
                duration_seconds=0,
            ),
            audit=AuditLog(log_path),
            alert_state=AlertState(state_path),
            dependencies=WatchDependencies(
                catalog_client=CatalogClient(transport),
                runtime=WatchRuntime(
                    monotonic=lambda: 10.0,
                    wall_clock=lambda: "2026-09-04T10:00:00+00:00",
                ),
            ),
        )

        summary = watch.run()

        assert summary.valid_window is True
        assert summary.account_check_count == 2
        assert [call[1]["Authorization"] for call in transport.calls] == [
            "Bearer access-a",
            "Bearer access-b",
        ]
        account_events: list[JsonObject] = []
        for event in events(log_path):
            if event["event_type"] == "account_catalog_check":
                account_events.append(event)
        assert [event["account_enabled"] for event in account_events] == [True, False]
        assert account_events[1]["broker_availability"] == "rate_limited"
        serialized = log_path.read_text()
        assert "access-a" not in serialized
        assert "access-b" not in serialized
        assert "must-never-be-used" not in serialized


def test_broker_auth_invalid_account_is_observed_without_request_or_refresh() -> None:
    """Exclude a broker-declared ended session while checking logged-in peers."""
    with temporary_path() as root:
        accounts_dir, log_path, state_path = private_paths(root)
        make_account(accounts_dir, "acc-a", "Logged in", enabled=True, token="access-a")
        make_account(
            accounts_dir, "acc-b", "Ended session", enabled=True, token="access-b"
        )
        _ = (accounts_dir / "acc-b" / "state.json").write_text(
            json.dumps({"availability": "auth_invalid"}),
        )
        transport = RecordingTransport({"models": [{"slug": "gpt-normal"}]})
        watch = AstraModelWatch(
            config=WatchConfig(
                accounts_dir=accounts_dir,
                client_version="0.137.0",
                duration_seconds=0,
            ),
            audit=AuditLog(log_path),
            alert_state=AlertState(state_path),
            dependencies=WatchDependencies(
                catalog_client=CatalogClient(transport),
                runtime=WatchRuntime(
                    monotonic=lambda: 10.0,
                    wall_clock=lambda: "2026-09-04T10:00:00+00:00",
                ),
            ),
        )

        summary = watch.run()

        assert summary.valid_window is True
        assert summary.account_observation_count == 2
        assert summary.account_check_count == 1
        assert summary.unavailable_observation_count == 1
        assert summary.provider_request_count == 1
        assert [call[1]["Authorization"] for call in transport.calls] == [
            "Bearer access-a"
        ]
        unavailable = next(
            event
            for event in events(log_path)
            if event.get("catalog_check_status") == "unavailable"
        )
        assert unavailable["account_label"] == "Ended session"
        assert unavailable["unavailable_reason"] == "broker_auth_invalid"
        assert unavailable["error_code"] is None
        unavailable_safety = cast("JsonObject", unavailable["safety"])
        assert unavailable_safety["provider_request_count"] == 0


def test_identity_mismatch_fails_closed_without_provider_request() -> None:
    """Refuse a bearer whose signed account identity does not match its directory."""
    with temporary_path() as root:
        accounts_dir, log_path, state_path = private_paths(root)
        make_account(accounts_dir, "acc-a", "A", enabled=True, token="access-a")
        auth_path = accounts_dir / "acc-a" / "auth.json"
        auth = cast("dict[str, object]", json.loads(auth_path.read_text()))
        tokens = cast("dict[str, object]", auth["tokens"])
        tokens["id_token"] = jwt_for("different-account")
        _ = auth_path.write_text(json.dumps(auth))
        auth_path.chmod(0o600)
        transport = RecordingTransport({"models": []})
        watch = AstraModelWatch(
            config=WatchConfig(
                accounts_dir=accounts_dir,
                client_version="0.137.0",
                duration_seconds=0,
            ),
            audit=AuditLog(log_path),
            alert_state=AlertState(state_path),
            dependencies=WatchDependencies(
                catalog_client=CatalogClient(transport),
                runtime=WatchRuntime(
                    monotonic=lambda: 10.0,
                    wall_clock=lambda: "2026-09-04T10:00:00+00:00",
                ),
            ),
        )

        summary = watch.run()

        assert summary.valid_window is False
        assert summary.error_count == 1
        assert not transport.calls
        event = next(
            event
            for event in events(log_path)
            if event["event_type"] == "account_catalog_check"
        )
        assert event["error_code"] == "auth_account_id_mismatch"
        assert event["safety"] == {
            "auth_refresh_attempted": False,
            "confidence": "code-enforced exact method/origin/path/query allowlist",
            "cookies_used": False,
            "generation_attempted": False,
            "lease_attempted": False,
            "provider_method_allowlist": ["GET"],
            "provider_path_allowlist": ["/backend-api/codex/models"],
            "provider_request_count": 0,
            "proxy_used": False,
            "redirects_followed": False,
            "request_body_sent": False,
            "reset_or_entitlement_endpoint_touched": False,
            "usage_endpoint_touched": False,
        }


def test_new_astra_match_alerts_once_across_restarts() -> None:
    """Send one private alert and persist a restart-safe hashed dedupe key."""
    with temporary_path() as root:
        accounts_dir, first_log, state_path = private_paths(root)
        make_account(accounts_dir, "acc-a", "A", enabled=True, token="access-a")
        transport = RecordingTransport({"models": [{"slug": "gpt-ASTRA-preview"}]})
        notifier = RecordingNotifier()
        config = WatchConfig(
            accounts_dir=accounts_dir,
            client_version="0.137.0",
            duration_seconds=0,
        )
        first = AstraModelWatch(
            config=config,
            audit=AuditLog(first_log),
            alert_state=AlertState(state_path),
            dependencies=WatchDependencies(
                catalog_client=CatalogClient(transport),
                notifier=notifier,
                runtime=WatchRuntime(
                    monotonic=lambda: 10.0,
                    wall_clock=lambda: "2026-09-04T10:00:00+00:00",
                ),
            ),
        )

        _ = first.run()

        assert notifier.preflight_count == 1
        assert len(notifier.messages) == 1
        assert "Account: A; model: gpt-ASTRA-preview" in notifier.messages[0]
        assert "no generation, lease, OAuth refresh" in notifier.messages[0]

        second_log = first_log.with_name("second.jsonl")
        second = AstraModelWatch(
            config=config,
            audit=AuditLog(second_log),
            alert_state=AlertState(state_path),
            dependencies=WatchDependencies(
                catalog_client=CatalogClient(transport),
                notifier=notifier,
                runtime=WatchRuntime(
                    monotonic=lambda: 20.0,
                    wall_clock=lambda: "2026-09-04T10:05:00+00:00",
                ),
            ),
        )
        _ = second.run()

        assert notifier.preflight_count == 2
        assert len(notifier.messages) == 1
