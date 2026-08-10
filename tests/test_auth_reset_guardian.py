from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from auth_reset_guardian.audit import SCHEMA_VERSION, AuditStore
from auth_reset_guardian.cli import _exclusive_lock
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
from auth_reset_guardian.models import (
    AccountDescriptor,
    AccountObservation,
    ProviderCredentials,
    ResetCredit,
    utc_iso,
)


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


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


def _hold_audit_lock(db_path: Path) -> int:
    lock_path = db_path.with_suffix(db_path.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


def test_exclusive_lock_waits_for_a_colliding_run_instead_of_failing(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    descriptor = _hold_audit_lock(db_path)

    def release() -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    timer = threading.Timer(0.05, release)
    timer.start()
    started = time.monotonic()
    with _exclusive_lock(db_path, wait_seconds=0.5):
        pass
    elapsed = time.monotonic() - started
    timer.join()

    assert elapsed >= 0.04


def test_exclusive_lock_still_fails_loudly_after_wait_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    descriptor = _hold_audit_lock(db_path)
    try:
        with pytest.raises(SystemExit, match="held the audit lock beyond"):
            with _exclusive_lock(db_path, wait_seconds=0.02):
                pass
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_deployment_live_dry_run_waits_for_quarter_hour_service() -> None:
    script = (ROOT / "ops" / "deploy_auth_reset_guardian.sh").read_text()

    assert 'readonly LOCK_WAIT_SECONDS="300"' in script
    assert (
        '--audit-db "${AUDIT_DB}" \\\n'
        '  --lock-wait-seconds "${LOCK_WAIT_SECONDS}" \\\n'
        "  run --dry-run --no-notify"
    ) in script


def test_schema_v1_migrates_warning_scope_without_losing_marks(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                account_count INTEGER NOT NULL DEFAULT 0,
                credit_count INTEGER NOT NULL DEFAULT 0,
                warning_count INTEGER NOT NULL DEFAULT 0,
                redemption_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT
            );
            CREATE TABLE warning_marks (
                mode TEXT NOT NULL,
                account_ref TEXT NOT NULL,
                credit_ref TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                threshold_hours INTEGER NOT NULL,
                first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                first_observed_at TEXT NOT NULL,
                PRIMARY KEY(mode, credit_ref, expires_at, threshold_hours)
            );
            INSERT INTO runs(run_id, mode, started_at, status)
            VALUES ('old-run', 'live', '2026-08-10T19:00:00Z', 'ok');
            INSERT INTO warning_marks(
                mode, account_ref, credit_ref, expires_at, threshold_hours,
                first_run_id, first_observed_at
            ) VALUES (
                'live', 'account-a', 'credit-a', '2026-08-11T21:08:33Z', 48,
                'old-run', '2026-08-10T19:00:00Z'
            );
            PRAGMA user_version = 1;
            """
        )

    with AuditStore(db_path):
        pass

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        table_info = connection.execute("PRAGMA table_info(warning_marks)").fetchall()
        primary_key = [row[1] for row in sorted(table_info, key=lambda row: row[5]) if row[5]]
        assert primary_key == [
            "mode",
            "account_ref",
            "credit_ref",
            "expires_at",
            "threshold_hours",
        ]
        retained = connection.execute(
            "SELECT mode, account_ref, credit_ref, expires_at, threshold_hours "
            "FROM warning_marks"
        ).fetchall()
        assert retained == [("live", "account-a", "credit-a", "2026-08-11T21:08:33Z", 48)]
        index_columns = [
            row[2]
            for row in connection.execute("PRAGMA index_info(redemption_open_idx)").fetchall()
        ]
        assert index_columns[:3] == ["account_ref", "credit_ref", "expires_at"]


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


def test_all_required_warning_thresholds_are_persisted_across_time(tmp_path: Path) -> None:
    initial = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    expiry = initial + timedelta(hours=49)
    clock = MutableClock(initial)
    source = SimulationSource(_fixture(expires_at=expiry), clock=clock)
    db_path = tmp_path / "audit.sqlite3"

    for remaining_hours in (47, 23, 5, 1.5, 0.5):
        clock.now = expiry - timedelta(hours=remaining_hours)
        with AuditStore(db_path) as audit:
            summary = Guardian(source=source, audit=audit, clock=clock).run(
                mode="threshold_coverage", dry_run=True
            )
        assert summary.warning_count == 1
        assert summary.redemption_attempt_count == 0

    thresholds = [
        event["threshold_hours"]
        for event in _events(db_path)
        if event["event_type"] == "expiry_warning"
    ]
    assert thresholds == [48, 24, 6, 2, 1]


def test_failed_live_warning_notification_retries_without_duplicate_warning(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 10, 21, 15, tzinfo=UTC)
    source = SimulationSource(
        _fixture(expires_at=now + timedelta(hours=23, minutes=53)),
        clock=lambda: now,
    )

    class FlakyNotifier:
        def __init__(self) -> None:
            self.calls = 0

        def notify(self, message: str) -> None:
            self.calls += 1
            assert "24h threshold" in message
            if self.calls == 1:
                raise NotificationError("temporary_failure")

    notifier = FlakyNotifier()
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        first = Guardian(
            source=source,
            audit=audit,
            notifier=notifier,  # type: ignore[arg-type]
            clock=lambda: now,
        ).run(mode="live", dry_run=True)
    with AuditStore(db_path) as audit:
        second = Guardian(
            source=source,
            audit=audit,
            notifier=notifier,  # type: ignore[arg-type]
            clock=lambda: now,
        ).run(mode="live", dry_run=True)

    assert first.warning_count == 2
    assert first.notification_error_count == 1
    assert first.status == "degraded"
    assert second.warning_count == 0
    assert second.notification_error_count == 0
    assert second.status == "ok"
    assert notifier.calls == 2
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT count(*) FROM warning_marks").fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM events WHERE event_type = 'expiry_warning'"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM notifications WHERE status = 'sent' AND attempts = 2"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM events WHERE event_type = 'notification_failed'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM events WHERE event_type = 'notification_sent'"
        ).fetchone()[0] == 1


def test_same_credit_id_and_expiry_are_scoped_per_account_for_warnings(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    fixture = _fixture(expires_at=now + timedelta(hours=5), credit_id="shared-provider-id")
    second = json.loads(json.dumps(fixture["accounts"][0]))
    second["label"] = "support@pitchai.net"
    fixture["accounts"].append(second)
    source = SimulationSource(fixture, clock=lambda: now)

    class RecordingNotifier:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def notify(self, message: str) -> None:
            self.messages.append(message)

    notifier = RecordingNotifier()
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(
            source=source,
            audit=audit,
            notifier=notifier,  # type: ignore[arg-type]
            clock=lambda: now,
        ).run(mode="live", dry_run=True)

    assert summary.warning_count == 6
    assert summary.redemption_attempt_count == 0
    assert len(notifier.messages) == 1
    assert "info@pitchai.net" in notifier.messages[0]
    assert "support@pitchai.net" in notifier.messages[0]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT count(*) FROM warning_marks").fetchone()[0] == 6
        assert connection.execute(
            "SELECT count(DISTINCT account_ref) FROM warning_marks"
        ).fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM notifications").fetchone()[0] == 6


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


def test_recheck_error_notification_is_scoped_by_expected_expiry(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)

    class RecordingNotifier:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def notify(self, message: str) -> None:
            self.messages.append(message)

    notifier = RecordingNotifier()
    db_path = tmp_path / "audit.sqlite3"
    expiries = (now + timedelta(hours=1), now + timedelta(hours=1, minutes=15))
    for expiry in expiries:
        fixture = _fixture(expires_at=expiry, credit_id="reused-provider-id")
        fixture["accounts"][0]["fail_on_refresh"] = 2
        source = SimulationSource(fixture, clock=lambda: now)
        with AuditStore(db_path) as audit:
            summary = Guardian(
                source=source,
                audit=audit,
                notifier=notifier,  # type: ignore[arg-type]
                clock=lambda: now,
            ).run(mode="live", dry_run=True)
        assert summary.redemption_attempt_count == 0
        assert summary.error_count == 1

    assert len(notifier.messages) == 2
    assert all("fresh redemption recheck failed" in message for message in notifier.messages)
    with sqlite3.connect(db_path) as connection:
        keys = connection.execute(
            "SELECT notification_key FROM notifications "
            "WHERE notification_key LIKE 'recheck-error:%' ORDER BY notification_key"
        ).fetchall()
        event_expiries = connection.execute(
            "SELECT expires_at FROM events "
            "WHERE event_type = 'redemption_recheck_failed' ORDER BY expires_at"
        ).fetchall()
    assert len(keys) == 2
    assert len({row[0] for row in keys}) == 2
    assert [row[0] for row in event_expiries] == sorted(utc_iso(expiry) for expiry in expiries)


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


def test_same_credit_id_and_expiry_do_not_resume_another_accounts_attempt(tmp_path: Path) -> None:
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    fixture = _fixture(
        expires_at=now + timedelta(hours=1),
        credit_id="shared-provider-id",
        outcome="reset",
    )
    second = json.loads(json.dumps(fixture["accounts"][0]))
    second["label"] = "support@pitchai.net"
    fixture["accounts"].append(second)

    class FirstAccountAmbiguousSource(SimulationSource):
        def consume_credit(self, observation, credit, idempotency_key):  # type: ignore[no-untyped-def]
            if observation.descriptor.label == "info@pitchai.net":
                self.consume_calls.append(
                    {
                        "account_ref": observation.descriptor.account_ref,
                        "credit_ref": credit.credit_ref,
                        "provider_id": credit.provider_id,
                        "idempotency_key": idempotency_key,
                    }
                )
                raise RemoteCallError(
                    endpoint="provider_consume_reset_credit",
                    error_code="transport_timeout",
                    ambiguous=True,
                )
            return super().consume_credit(observation, credit, idempotency_key)

    source = FirstAccountAmbiguousSource(fixture, clock=lambda: now)
    db_path = tmp_path / "audit.sqlite3"
    with AuditStore(db_path) as audit:
        summary = Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation", dry_run=False
        )

    assert summary.redemption_attempt_count == 2
    assert summary.redemption_count == 1
    assert summary.error_count == 1
    assert len(source.consume_calls) == 2
    assert len({call["account_ref"] for call in source.consume_calls}) == 2
    assert len({call["idempotency_key"] for call in source.consume_calls}) == 2
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT account_ref, idempotency_key FROM redemption_attempts"
        ).fetchall()
    assert len(rows) == 2
    assert len({row[0] for row in rows}) == 2
    assert len({row[1] for row in rows}) == 2


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


def test_invalid_consume_result_is_ambiguous_and_reuses_exact_idempotency_key() -> None:
    expiry = datetime(2026, 8, 11, 21, 8, 33, tzinfo=UTC)

    class InvalidResultHttp:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def request(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(kwargs)
            assert kwargs["endpoint"] == "provider_consume_reset_credit"
            return {"code": "unsupported-provider-result", "windows_reset": 0}

    http = InvalidResultHttp()
    source = BrokerProviderSource(
        broker_url="http://broker.invalid",
        broker_admin_token="broker-admin-secret",
        provider_base_url="https://provider.invalid/backend-api",
        http=http,  # type: ignore[arg-type]
    )
    descriptor = AccountDescriptor(
        broker_account_id="broker-account-secret",
        label="info@pitchai.net",
        enabled=True,
    )
    credit = ResetCredit.from_provider(
        _credit(credit_id="provider-credit-secret", expires_at=expiry)
    )
    observation = AccountObservation(
        descriptor=descriptor,
        captured_at=expiry - timedelta(hours=1),
        broker_state={"availability": "available"},
        usage_state={},
        available_count=1,
        credits=(credit,),
        credentials=ProviderCredentials(
            access_token="fixture-oauth",
            account_id="chatgpt-account-secret",
        ),
    )

    with pytest.raises(RemoteCallError) as captured:
        source.consume_credit(observation, credit, "durable-key")
    assert captured.value.ambiguous is True
    assert captured.value.error_code == "invalid_result_payload"
    assert len(http.calls) == 2
    assert {call["payload"]["redeem_request_id"] for call in http.calls} == {"durable-key"}
    assert {call["payload"]["credit_id"] for call in http.calls} == {
        "provider-credit-secret"
    }


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


def test_command_notifier_child_does_not_inherit_broker_or_openai_secrets(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    secret_names = (
        "AUTH_RESET_GUARDIAN_BROKER_ADMIN_TOKEN",
        "AUTH_TOKEN_SERVER_ADMIN_TOKEN",
        "AUTH_TOKEN_SERVER_ADMIN_TOKEN_ALIASES",
        "AUTH_TOKEN_SERVER_CLIENT_TOKEN",
        "AUTH_TOKEN_SERVER_CLIENT_TOKEN_ALIASES",
        "OPENAI_API_KEY",
    )
    for name in secret_names:
        monkeypatch.setenv(name, f"secret-{name.lower()}")
    receipt = {
        "status": "sent",
        "policy": "personal-first",
        "route_kind": "private",
        "requester_key": "seth-ori",
        "destination_ref": "seth-ori",
    }
    child_code = (
        "import json, os; "
        f"names = {secret_names!r}; "
        "assert not any(os.environ.get(name) for name in names); "
        f"print(json.dumps({receipt!r}))"
    )

    CommandNotifier([sys.executable, "-c", child_code]).notify("safe message")


def test_alert_batches_never_mark_unreported_overflow_as_sent() -> None:
    alerts = [Alert(key=f"alert-{index}", line="x" * 100) for index in range(100)]
    batches = _alert_batches(alerts)
    assert len(batches) > 1
    assert [alert.key for batch in batches for alert in batch] == [alert.key for alert in alerts]
    assert all(
        len("\n".join(["<b>Codex reset guardian</b>", *[alert.line for alert in batch]])) <= 3800
        for batch in batches
    )
