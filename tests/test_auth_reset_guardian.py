from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.clients import (
    AccountScanError,
    BrokerProviderSource,
    RemoteCallError,
    SimulationSource,
)
from auth_reset_guardian.guardian import (
    Alert,
    CommandNotifier,
    Guardian,
    NotificationError,
    _alert_batches,
)
from auth_reset_guardian.models import utc_iso


UTC = timezone.utc


class MutableClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _credit(*, credit_id: str, expires_at: datetime, status: str = "available") -> dict:
    return {
        "id": credit_id,
        "reset_type": "codex_rate_limits",
        "status": status,
        "granted_at": utc_iso(expires_at - timedelta(days=30)),
        "expires_at": utc_iso(expires_at),
        "title": "Full reset",
        "is_supported_by_plan": True,
    }


def _fixture(
    *,
    expires_at: datetime,
    credit_id: str = "opaque-provider-credit",
    outcome: str = "nothing_to_reset",
) -> dict:
    return {
        "accounts": [
            {
                "label": "info@pitchai.net",
                "broker_availability": "available",
                "usage": {
                    "rate_limit": {
                        "allowed": True,
                        "limit_reached": False,
                        "primary_window": {
                            "limit_window_seconds": 604800,
                            "reset_after_seconds": 1200,
                            "reset_at": int((expires_at + timedelta(days=3)).timestamp()),
                            "used_percent": 5,
                        },
                        "secondary_window": None,
                    },
                    "rate_limit_reset_credits": {
                        "available_count": 1,
                        "applicable_available_count": 0,
                    },
                },
                "credit_inventory": {
                    "available_count": 1,
                    "credits": [_credit(credit_id=credit_id, expires_at=expires_at)],
                },
                "consume_outcomes": {
                    credit_id: [{"code": outcome, "windows_reset": 2 if outcome == "reset" else 0}]
                },
            }
        ]
    }


def _events(db_path: Path) -> list[dict]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM events ORDER BY event_id")]


def test_warning_thresholds_are_emitted_once_per_mode_across_restarts(tmp_path: Path) -> None:
    now = datetime(2026, 8, 10, 19, 0, tzinfo=UTC)
    clock = MutableClock(now)
    source = SimulationSource(_fixture(expires_at=now + timedelta(hours=26)), clock=clock)
    db_path = tmp_path / "audit.sqlite3"

    with AuditStore(db_path) as audit:
        first = Guardian(source=source, audit=audit, clock=clock).run(mode="simulation", dry_run=False)
    assert first.warning_count == 1
    assert first.redemption_attempt_count == 0

    with AuditStore(db_path) as audit:
        second = Guardian(source=source, audit=audit, clock=clock).run(mode="simulation", dry_run=False)
    assert second.warning_count == 0

    clock.now = now + timedelta(hours=3)
    with AuditStore(db_path) as audit:
        third = Guardian(source=source, audit=audit, clock=clock).run(mode="simulation", dry_run=False)
    assert third.warning_count == 1
    thresholds = [event["threshold_hours"] for event in _events(db_path) if event["event_type"] == "expiry_warning"]
    assert thresholds == [48, 24]


def test_simulation_redeems_exact_credit_after_fresh_recheck(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 19, 45, tzinfo=UTC)
    expiry = now + timedelta(minutes=83)
    clock = MutableClock(now)
    source = SimulationSource(
        _fixture(expires_at=expiry, credit_id="exact-credit-a", outcome="reset"),
        clock=clock,
    )
    with AuditStore(tmp_path / "audit.sqlite3") as audit:
        summary = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation", dry_run=False
        )

    assert summary.warning_count == 4
    assert summary.redemption_attempt_count == 1
    assert summary.redemption_count == 1
    assert summary.error_count == 0
    assert len(source.consume_calls) == 1
    assert source.consume_calls[0]["provider_id"] == "exact-credit-a"
    assert source.refresh_calls[next(iter(source.refresh_calls))] == 3


def test_live_style_dry_run_performs_fresh_recheck_but_never_consumes(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    clock = MutableClock(now)
    source = SimulationSource(_fixture(expires_at=now + timedelta(hours=1)), clock=clock)
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=clock).run(
            mode="dry_run", dry_run=True
        )
    assert summary.redemption_attempt_count == 0
    assert source.consume_calls == []
    assert next(iter(source.refresh_calls.values())) == 2
    assert any(event["event_type"] == "redemption_suppressed_dry_run" for event in _events(db_path))


def test_credit_removed_between_inventory_and_recheck_is_not_replaced_by_another_credit(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    expiry = now + timedelta(hours=1)

    class RacingSource(SimulationSource):
        def refresh_account(self, descriptor):  # type: ignore[no-untyped-def]
            observation = super().refresh_account(descriptor)
            if self.refresh_calls[descriptor.account_ref] == 1:
                self.remove_credit_before_next_refresh(
                    label="info@pitchai.net", provider_id="earliest-credit"
                )
            return observation

    fixture = _fixture(expires_at=expiry, credit_id="earliest-credit", outcome="reset")
    fixture["accounts"][0]["credit_inventory"]["credits"].append(
        _credit(credit_id="later-credit", expires_at=now + timedelta(days=1))
    )
    fixture["accounts"][0]["credit_inventory"]["available_count"] = 2
    source = RacingSource(fixture, clock=lambda: now)
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation", dry_run=False
        )
    assert summary.redemption_attempt_count == 0
    assert source.consume_calls == []
    assert any(
        event["event_type"] == "redemption_skipped_after_fresh_recheck"
        for event in _events(db_path)
    )


def test_same_credit_id_with_changed_expiry_fails_loudly_without_consuming(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    selected_expiry = now + timedelta(hours=1)
    changed_expiry = selected_expiry + timedelta(minutes=15)

    class ExpiryChangedSource(SimulationSource):
        def refresh_account(self, descriptor):  # type: ignore[no-untyped-def]
            observation = super().refresh_account(descriptor)
            if self.refresh_calls[descriptor.account_ref] == 1:
                account = self._find(descriptor)
                account["credit_inventory"]["credits"][0]["expires_at"] = utc_iso(
                    changed_expiry
                )
            return observation

    source = ExpiryChangedSource(
        _fixture(
            expires_at=selected_expiry,
            credit_id="same-opaque-credit",
            outcome="reset",
        ),
        clock=lambda: now,
    )
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation", dry_run=False
        )

    assert summary.redemption_attempt_count == 0
    assert summary.redemption_count == 0
    assert summary.error_count == 1
    assert source.consume_calls == []
    mismatch_events = [
        event
        for event in _events(db_path)
        if event["event_type"] == "redemption_skipped_expiry_mismatch"
    ]
    assert len(mismatch_events) == 1
    assert mismatch_events[0]["severity"] == "error"


def test_nothing_to_reset_is_retried_with_a_new_logical_idempotency_key(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    clock = MutableClock(now)
    fixture = _fixture(expires_at=now + timedelta(hours=1), outcome="nothing_to_reset")
    fixture["accounts"][0]["consume_outcomes"]["opaque-provider-credit"].append(
        {"code": "nothing_to_reset", "windows_reset": 0}
    )
    source = SimulationSource(fixture, clock=clock)
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        first = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation", dry_run=False
        )
    clock.now += timedelta(minutes=15)
    with AuditStore(db_path) as audit:
        second = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation", dry_run=False
        )
    assert first.redemption_attempt_count == second.redemption_attempt_count == 1
    assert len(source.consume_calls) == 2
    assert source.consume_calls[0]["idempotency_key"] != source.consume_calls[1]["idempotency_key"]


def test_ambiguous_attempt_resumes_the_same_idempotency_key(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    clock = MutableClock(now)

    class AmbiguousThenSuccessSource(SimulationSource):
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            self.keys: list[str] = []

        def consume_credit(self, observation, credit, idempotency_key):  # type: ignore[no-untyped-def]
            self.keys.append(idempotency_key)
            if len(self.keys) == 1:
                raise RemoteCallError(
                    endpoint="provider_consume_reset_credit",
                    error_code="transport_timeout",
                    ambiguous=True,
                )
            return super().consume_credit(observation, credit, idempotency_key)

    source = AmbiguousThenSuccessSource(
        _fixture(expires_at=now + timedelta(hours=1), outcome="reset"), clock=clock
    )
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        first = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation", dry_run=False
        )
    clock.now += timedelta(minutes=15)
    with AuditStore(db_path) as audit:
        second = Guardian(source=source, audit=audit, clock=clock).run(
            mode="simulation", dry_run=False
        )
    assert first.error_count == 1
    assert second.redemption_count == 1
    assert source.keys[0] == source.keys[1]


def test_audit_never_contains_raw_provider_ids_or_auth_material(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    raw_credit_id = "opaque-credit-secret-value"
    db_path = tmp_path / "audit.sqlite3"
    source = SimulationSource(
        _fixture(expires_at=now + timedelta(hours=3), credit_id=raw_credit_id),
        clock=lambda: now,
    )
    with AuditStore(db_path) as audit:
        Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation", dry_run=False
        )
    database_bytes = db_path.read_bytes()
    assert raw_credit_id.encode() not in database_bytes
    assert b"access_token" not in database_bytes
    assert b"refresh_token" not in database_bytes
    assert b"Authorization" not in database_bytes


def test_manual_redemption_requires_exact_expiry_and_uses_two_reads(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    expiry = now + timedelta(hours=12)
    source = SimulationSource(
        _fixture(expires_at=expiry, credit_id="manual-credit", outcome="reset"),
        clock=lambda: now,
    )
    with AuditStore(tmp_path / "audit.sqlite3") as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).manual_redeem(
            account_label="info@pitchai.net",
            expires_at=expiry,
            reason="operator-confirmed-test",
            dry_run=False,
        )
    assert summary.redemption_count == 1
    assert len(source.consume_calls) == 1
    assert next(iter(source.refresh_calls.values())) == 3


def test_simulation_fixture_round_trip_is_valid_json(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(_fixture(expires_at=now + timedelta(hours=1))), encoding="utf-8")
    source = SimulationSource.from_path(fixture_path, clock=lambda: now)
    assert source.list_accounts()[0].label == "info@pitchai.net"


def test_live_source_uses_only_broker_oauth_and_targets_exact_credit() -> None:
    expiry = datetime(2026, 8, 11, 21, 8, 33, tzinfo=UTC)

    class FakeHttp:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def request(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(kwargs)
            endpoint = kwargs["endpoint"]
            if endpoint == "broker_list_accounts":
                return {
                    "accounts": [
                        {
                            "metadata": {
                                "account_id": "broker-account-secret",
                                "label": "info@pitchai.net",
                                "enabled": True,
                                "priority": 10,
                            }
                        }
                    ]
                }
            if endpoint == "broker_analytics_probe":
                return {
                    "metadata": {"label": "info@pitchai.net"},
                    "state": {
                        "availability": "available",
                        "last_probe_at": "2026-08-10T19:00:00Z",
                        "analytics": {"errors": {}},
                    },
                }
            if endpoint == "broker_export_auth":
                return {
                    "OPENAI_API_KEY": "must-never-be-used",
                    "tokens": {
                        "access_token": "fixture-oauth",
                        "refresh_token": "fixture-refresh",
                        "account_id": "chatgpt-account-secret",
                    },
                }
            if endpoint == "provider_usage":
                return {
                    "rate_limit": {
                        "allowed": False,
                        "limit_reached": True,
                        "primary_window": {"used_percent": 100},
                        "secondary_window": None,
                    },
                    "rate_limit_reset_credits": {
                        "available_count": 1,
                        "applicable_available_count": 1,
                    },
                }
            if endpoint == "provider_reset_credits":
                return {
                    "available_count": 1,
                    "credits": [_credit(credit_id="provider-credit-secret", expires_at=expiry)],
                }
            if endpoint == "provider_consume_reset_credit":
                assert kwargs["payload"]["credit_id"] == "provider-credit-secret"
                assert kwargs["payload"]["redeem_request_id"] == "durable-key"
                return {"code": "reset", "windows_reset": 2}
            raise AssertionError(endpoint)

    http = FakeHttp()
    source = BrokerProviderSource(
        broker_url="http://broker.invalid",
        broker_admin_token="broker-admin-secret",
        provider_base_url="https://provider.invalid/backend-api",
        http=http,  # type: ignore[arg-type]
    )
    descriptor = source.list_accounts()[0]
    observation = source.refresh_account(descriptor)
    result = source.consume_credit(observation, observation.credits[0], "durable-key")
    assert result.code == "reset"
    provider_calls = [call for call in http.calls if call["endpoint"].startswith("provider_")]
    assert provider_calls
    for call in provider_calls:
        assert call["headers"]["Authorization"] == "Bearer fixture-oauth"
        assert call["headers"]["ChatGPT-Account-Id"] == "chatgpt-account-secret"
        serialized = json.dumps(call)
        assert "must-never-be-used" not in serialized
        assert "fixture-refresh" not in serialized


def test_live_source_stops_after_broker_reports_auth_invalid() -> None:
    class FakeHttp:
        def __init__(self) -> None:
            self.endpoints: list[str] = []

        def request(self, **kwargs):  # type: ignore[no-untyped-def]
            self.endpoints.append(kwargs["endpoint"])
            if kwargs["endpoint"] == "broker_list_accounts":
                return {
                    "accounts": [
                        {
                            "metadata": {
                                "account_id": "invalid-account",
                                "label": "sales@pitchai.net",
                                "enabled": True,
                            }
                        }
                    ]
                }
            if kwargs["endpoint"] == "broker_analytics_probe":
                return {
                    "metadata": {"label": "sales@pitchai.net"},
                    "state": {"availability": "auth_invalid", "analytics": {"errors": {}}},
                }
            raise AssertionError("auth-invalid account must not be exported or called at provider")

    http = FakeHttp()
    source = BrokerProviderSource(
        broker_url="http://broker.invalid",
        broker_admin_token="broker-admin-secret",
        http=http,  # type: ignore[arg-type]
    )
    descriptor = source.list_accounts()[0]
    try:
        source.refresh_account(descriptor)
    except AccountScanError as exc:
        assert exc.error_code == "broker_auth_invalid"
    else:
        raise AssertionError("auth-invalid broker account must fail loudly")
    assert http.endpoints == ["broker_list_accounts", "broker_analytics_probe"]


def test_command_notifier_requires_verified_requester_private_receipt(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    private_receipt = json.dumps(
        {
            "status": "sent",
            "policy": "personal-first",
            "route_kind": "private",
            "requester_key": "seth-ori",
            "destination_ref": "seth-ori",
        }
    )
    monkeypatch.setattr(
        "auth_reset_guardian.guardian.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=private_receipt, stderr=""),
    )
    CommandNotifier(["telegram-helper"]).notify("safe message")

    broad_receipt = private_receipt.replace('"private"', '"group"')
    monkeypatch.setattr(
        "auth_reset_guardian.guardian.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=broad_receipt, stderr=""),
    )
    try:
        CommandNotifier(["telegram-helper"]).notify("must fail closed")
    except NotificationError as exc:
        assert exc.error_code == "invalid_private_receipt"
    else:
        raise AssertionError("broad receipt must fail requester-private verification")


def test_alert_batches_never_mark_unreported_overflow_as_sent() -> None:
    alerts = [Alert(key=f"alert-{index}", line="x" * 100) for index in range(100)]
    batches = _alert_batches(alerts)
    assert len(batches) > 1
    assert [alert.key for batch in batches for alert in batch] == [alert.key for alert in alerts]
    assert all(
        len("\n".join(["<b>Codex reset guardian</b>", *[alert.line for alert in batch]])) <= 3800
        for batch in batches
    )
