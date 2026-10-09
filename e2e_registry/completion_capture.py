# Copyright (c) 2026 PitchAI. All rights reserved.
"""Atomic, future-only capture of reviewed registry run completions."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class RegistrySource:
    """A reviewed registry identity, deliberately not an Engine identity."""

    tenant_id: str
    test_id: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_completion_sources (
    tenant_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    PRIMARY KEY (tenant_id, test_id)
);
CREATE TABLE IF NOT EXISTS registry_completion_outbox (
    run_id TEXT PRIMARY KEY,
    registry_tenant_id TEXT NOT NULL,
    registry_test_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    body_json TEXT NOT NULL,
    delivery_json TEXT,
    receiver_event_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    lease_token TEXT,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS registry_completion_due
    ON registry_completion_outbox(receiver_event_id, next_attempt_at);
CREATE TRIGGER IF NOT EXISTS registry_completion_capture_v1
AFTER UPDATE OF status ON runs
WHEN OLD.finished_at_ts IS NULL
 AND (OLD.error_kind = 'pending' OR OLD.status NOT IN ('pass', 'fail', 'infra_degraded'))
 AND NEW.status IN ('pass', 'fail', 'infra_degraded')
BEGIN
    INSERT INTO registry_completion_outbox (
        run_id, registry_tenant_id, registry_test_id, captured_at, body_json
    )
    SELECT NEW.id, t.tenant_id, t.id, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
        json_object(
            'registry_tenant_id', t.tenant_id,
            'registry_test_id', t.id,
            'registry_run_id', NEW.id,
            'test_name', t.name,
            'status', NEW.status,
            'started_at_ts', NEW.started_at_ts,
            'finished_at_ts', NEW.finished_at_ts,
            'elapsed_ms', NEW.elapsed_ms,
            'error_kind', NEW.error_kind,
            'error_message', NEW.error_message,
            'final_url', NEW.final_url,
            'title', NEW.title,
            'artifacts', json(NEW.artifacts_json)
        )
    FROM tests t
    JOIN registry_completion_sources s
        ON s.tenant_id = t.tenant_id AND s.test_id = t.id
    WHERE t.id = NEW.test_id
    ON CONFLICT(run_id) DO NOTHING;
END;
"""


def install_capture(db_path: str, sources: tuple[RegistrySource, ...]) -> None:
    """Install future completion capture without scanning or changing old runs.

    Updating the reviewed source set leaves already captured obligations intact.
    Each trigger insert commits or rolls back with its original run update.

    Raises:
        ValueError: A requested source lacks its exact registry tenant/test pair.
    """
    # Schema installation itself is atomic; no partially installed trigger
    # may survive a failed source-set validation below.
    with (
        closing(sqlite3.connect(db_path, isolation_level=None)) as connection,
        connection as transaction,
    ):
        _ = transaction.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        for source in sources:
            found = cast("object", connection.execute(
                "SELECT 1 FROM tests WHERE id = ? AND tenant_id = ?",
                (source.test_id, source.tenant_id),
            ).fetchone())
            if found is None:
                message = "Registry completion source does not match its exact tenant/test identity."
                raise ValueError(message)
        _ = connection.execute("DELETE FROM registry_completion_sources")
        _ = connection.executemany(
            "INSERT INTO registry_completion_sources(tenant_id, test_id) VALUES (?, ?)",
            [(source.tenant_id, source.test_id) for source in sources],
        )
