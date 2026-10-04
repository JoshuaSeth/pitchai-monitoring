# Copyright (c) 2026 PitchAI. All rights reserved.
"""Disposable transaction proof for registry completion source capture."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast, final

import pytest

from . import db
from .completion_capture import RegistrySource, install_capture
from .settings import RegistrySettings

type Row = tuple[str | int | float | None, ...]
type Evidence = str | int | float | bool | list[Evidence] | tuple[Evidence, ...] | dict[str, Evidence] | None


def expect_equal(actual: Evidence, expected: Evidence) -> None:
    """Compare durable evidence without optimized-away Python assertions.

    Raises:
        AssertionError: The observed value differs from the required evidence.
    """
    if actual != expected:
        message = f"Expected {expected!r}; observed {actual!r}"
        raise AssertionError(message)


@final
@pytest.mark.usefixtures("setup_registry")
class TestCompletionCapture:
    """Exercise rollback, duplicate delivery and exact source fencing."""

    path: str = ""
    source: tuple[RegistrySource, ...] = ()

    @pytest.fixture
    def setup_registry(self, tmp_path: Path) -> None:
        """Create disposable registry columns with the real pending-run shape."""
        self.path = str(tmp_path / "registry.db")
        self.source = (RegistrySource("registry-owner", "reviewed"),)
        with closing(sqlite3.connect(self.path)) as connection:
            _ = connection.executescript("""
                CREATE TABLE tests (id TEXT PRIMARY KEY, tenant_id TEXT, name TEXT);
                CREATE TABLE runs (
                    id TEXT PRIMARY KEY, test_id TEXT, status TEXT,
                    started_at_ts REAL, finished_at_ts REAL, elapsed_ms INTEGER,
                    error_kind TEXT, error_message TEXT, final_url TEXT,
                    title TEXT, artifacts_json TEXT
                );
                INSERT INTO tests VALUES ('reviewed', 'registry-owner', 'AFAS canary');
                INSERT INTO tests VALUES ('other', 'other-owner', 'Unrelated');
                INSERT INTO runs(id, test_id, status, error_kind, artifacts_json)
                    VALUES ('original', 'reviewed', 'infra_degraded', 'pending', '{}');
                INSERT INTO runs(id, test_id, status, finished_at_ts, artifacts_json)
                    VALUES ('old', 'reviewed', 'fail', 1, '{}');
                INSERT INTO runs(id, test_id, status, artifacts_json)
                    VALUES ('unrelated', 'other', 'infra_degraded', '{}');
            """)

    def test_original_completion_is_atomic_exact_and_once(self) -> None:
        """A committed result keeps its source identity and full evidence on retry."""
        install_capture(self.path, self.source)
        body = "Actual failed answer: café\n" + "full result " * 1000
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                _ = connection.execute(
                    """UPDATE runs SET status='fail', finished_at_ts=1780000000.5,
                    elapsed_ms=240000, error_kind='answer', error_message=?,
                    artifacts_json='{"screenshot":"private.png"}' WHERE id='original'""",
                    (body,),
                )
            stored = cast("Row", connection.execute(
                "SELECT run_id, registry_tenant_id, registry_test_id, body_json FROM registry_completion_outbox",
            ).fetchone())
            expect_equal(stored[:3], ("original", "registry-owner", "reviewed"))
            payload = cast("dict[str, Evidence]", json.loads(str(stored[3])))
            expect_equal(payload["error_message"], body)
            expect_equal(payload["artifacts"], {"screenshot": "private.png"})
            expect_equal(payload["finished_at_ts"], 1780000000.5)
            with connection:
                _ = connection.execute("UPDATE runs SET status='fail', error_message='retry' WHERE id='original'")
            repeated = cast("Row", connection.execute("SELECT body_json FROM registry_completion_outbox").fetchone())
            expect_equal(repeated[0], stored[3])

    def test_rollback_and_no_historical_backfill(self) -> None:
        """An uncommitted completion and a pre-install failure create no event."""
        install_capture(self.path, self.source)
        with closing(sqlite3.connect(self.path)) as connection:
            _ = connection.execute("UPDATE runs SET status='pass', finished_at_ts=10 WHERE id='original'")
            expect_equal(cast("Row", connection.execute(
                "SELECT count(*) FROM registry_completion_outbox",
            ).fetchone()), (1,))
            connection.rollback()
            expect_equal(cast("Row", connection.execute(
                "SELECT count(*) FROM registry_completion_outbox",
            ).fetchone()), (0,))
            with connection:
                _ = connection.execute("UPDATE runs SET status='fail', finished_at_ts=10 WHERE id='old'")
                _ = connection.execute("UPDATE runs SET status='fail', finished_at_ts=10 WHERE id='unrelated'")
            expect_equal(cast("Row", connection.execute(
                "SELECT count(*) FROM registry_completion_outbox",
            ).fetchone()), (0,))

    def test_wrong_tenant_does_not_replace_reviewed_sources(self) -> None:
        """Source changes cannot silently substitute another tenant."""
        install_capture(self.path, self.source)
        with pytest.raises(ValueError, match="exact tenant/test"):
            install_capture(self.path, (RegistrySource("other-owner", "reviewed"),))
        with closing(sqlite3.connect(self.path)) as connection:
            expect_equal(cast("list[Evidence]", connection.execute(
                "SELECT * FROM registry_completion_sources",
            ).fetchall()), [
                ("registry-owner", "reviewed"),
            ])

    def test_removal_preserves_pending_original(self) -> None:
        """Source retirement stops new capture without purging an obligation."""
        install_capture(self.path, self.source)
        with (closing(sqlite3.connect(self.path)) as connection, connection as transaction):
            _ = transaction.execute("UPDATE runs SET status='infra_degraded', finished_at_ts=10 WHERE id='original'")
        install_capture(self.path, ())
        with (closing(sqlite3.connect(self.path)) as connection, connection as transaction):
            _ = transaction.execute(
                """INSERT INTO runs(id,test_id,status,error_kind,artifacts_json)
                VALUES ('next','reviewed','infra_degraded','pending','{}')""",
            )
            _ = connection.execute("UPDATE runs SET status='fail', finished_at_ts=11 WHERE id='next'")
            expect_equal(cast("list[Evidence]", connection.execute(
                "SELECT run_id FROM registry_completion_outbox",
            ).fetchall()), [("original",)])

    def test_real_registry_claim_and_completion_capture_original_run(self) -> None:
        """The public registry writer commits exactly one original source record."""
        path = str(Path(self.path).with_name("actual.db"))
        settings = RegistrySettings(db_path=path, alerts_enabled=False, dispatch_enabled=False)
        tenant = cast("dict[str, object]", db.create_tenant(settings, name="owned disposable"))
        tenant_id = str(tenant["id"])
        _ = db.insert_test(
            settings, tenant_id=tenant_id, test_id="actual", name="actual schema",
            base_url="https://example.invalid", interval_seconds=300,
            timeout_seconds=240, jitter_seconds=0, down_after_failures=1,
            up_after_successes=1, notify_on_recovery=False, dispatch_on_failure=False,
        )
        install_capture(path, (RegistrySource(tenant_id, "actual"),))
        claimed = db.claim_due_runs(settings, max_runs=1)
        expect_equal(len(claimed), 1)
        run_id = claimed[0].run_id
        completion = db.RunCompletion(
            status="fail", elapsed_ms=240000, error_kind="answer", error_message="actual complete response",
            final_url=None, title=None, artifacts={}, started_at_ts=1, finished_at_ts=241,
        )
        outcome = db.complete_run(settings, run_id=run_id, completion=completion)
        expect_equal(outcome.updated, expected=True)
        _ = db.complete_run(settings, run_id=run_id, completion=completion)
        with closing(sqlite3.connect(path)) as connection:
            rows = cast("list[Evidence]", connection.execute(
                "SELECT run_id, registry_tenant_id, registry_test_id FROM registry_completion_outbox",
            ).fetchall())
        expect_equal(rows, [(run_id, tenant_id, "actual")])

    def test_optional_runner_finish_time_does_not_drop_completion(self) -> None:
        """The legacy runner accepts absent timestamps; its result still matters."""
        install_capture(self.path, self.source)
        with (closing(sqlite3.connect(self.path)) as connection, connection as transaction):
            _ = transaction.execute(
                "UPDATE runs SET status='pass', error_kind=NULL, error_message=NULL WHERE id='original'",
            )
            row = cast("Row", connection.execute(
                "SELECT body_json FROM registry_completion_outbox",
            ).fetchone())
        payload = cast("dict[str, Evidence]", json.loads(str(row[0])))
        expect_equal(payload["finished_at_ts"], None)
        expect_equal(payload["status"], "pass")
