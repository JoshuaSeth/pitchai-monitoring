# Copyright (c) 2026 PitchAI. All rights reserved.
"""Atomic run claiming for the E2E registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.db_core import fetch_all_rows, new_uuid, row_record, utc_timestamp
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import (
    ClaimedRun,
    parse_json_object,
    require_integer,
    require_text,
)

if TYPE_CHECKING:
    from e2e_registry.models import (
        DatabaseRecord,
    )
    from e2e_registry.settings import RegistrySettings

_MAX_CLAIM_COUNT = 50
_MINIMUM_LOCK_TIMEOUT_SECONDS = 10
_DEFAULT_TEST_TIMEOUT_SECONDS = 45


def _optional_text(record: DatabaseRecord, key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    text = require_text(value, label=key).strip()
    return text or None


def _claimed_run(record: DatabaseRecord, *, run_id: str) -> ClaimedRun:
    definition = parse_json_object(
        record.get("definition_json"),
        label="definition_json",
        empty_when_missing=True,
    )
    raw_test_kind = _optional_text(record, "test_kind")
    test_kind = raw_test_kind.lower() if raw_test_kind is not None else "stepflow"
    return ClaimedRun(
        run_id=run_id,
        test_id=require_text(record.get("test_id"), label="test_id"),
        tenant_id=require_text(record.get("tenant_id"), label="tenant_id"),
        test_name=require_text(record.get("test_name"), label="test_name"),
        base_url=require_text(record.get("base_url"), label="base_url"),
        timeout_seconds=require_integer(
            record.get("timeout_seconds") or _DEFAULT_TEST_TIMEOUT_SECONDS,
            label="timeout_seconds",
        ),
        test_kind=test_kind or "stepflow",
        definition=definition,
        source_relpath=_optional_text(record, "source_relpath"),
        source_filename=_optional_text(record, "source_filename"),
        source_sha256=_optional_text(record, "source_sha256"),
    )


def claim_due_runs(settings: RegistrySettings, *, max_runs: int) -> list[ClaimedRun]:
    """Claim due tests and create unfinished run records for a runner.

    Returns:
        Runs whose locks are now owned by the calling runner.
    """
    bounded_count = max(0, min(max_runs, _MAX_CLAIM_COUNT))
    if bounded_count == 0:
        return []
    now = utc_timestamp()
    lock_timeout = max(
        _MINIMUM_LOCK_TIMEOUT_SECONDS,
        settings.runner_lock_timeout_seconds,
    )
    lock_cutoff = now - lock_timeout
    with registry_connection(settings) as connection:
        claimed: list[ClaimedRun] = []
        with connection:
            connection.execute("BEGIN IMMEDIATE;")
            rows = fetch_all_rows(
                connection.execute(
                    """
                SELECT
                  t.id AS test_id,
                  t.tenant_id AS tenant_id,
                  t.name AS test_name,
                  t.base_url AS base_url,
                  t.timeout_seconds AS timeout_seconds,
                  t.test_kind AS test_kind,
                  t.definition_json AS definition_json,
                  t.source_relpath AS source_relpath,
                  t.source_filename AS source_filename,
                  t.source_sha256 AS source_sha256
                FROM tests t
                JOIN test_state s ON s.test_id=t.id
                WHERE
                  t.enabled=1
                  AND (t.disabled_until_ts IS NULL OR t.disabled_until_ts <= ?)
                  AND (s.next_due_ts IS NULL OR s.next_due_ts <= ?)
                  AND (
                    s.running_lock_id IS NULL
                    OR s.running_locked_at_ts IS NULL
                    OR s.running_locked_at_ts < ?
                  )
                ORDER BY COALESCE(s.next_due_ts, 0) ASC, t.created_at_ts ASC
                LIMIT ?
                """,
                    (now, now, lock_cutoff, bounded_count),
                ),
            )
            for row in rows:
                record = row_record(row)
                run_id = new_uuid()
                claimed_run = _claimed_run(record, run_id=run_id)
                connection.execute(
                    "UPDATE test_state SET running_lock_id=?, running_locked_at_ts=? WHERE test_id=?",
                    (run_id, now, claimed_run.test_id),
                )
                connection.execute(
                    """
                    INSERT INTO runs (
                      id, test_id, scheduled_for_ts, started_at_ts, finished_at_ts,
                      status, elapsed_ms, error_kind, error_message, final_url, title, artifacts_json
                    ) VALUES (?, ?, ?, NULL, NULL, 'infra_degraded', NULL, 'pending', NULL, NULL, NULL, '{}')
                    """,
                    (run_id, claimed_run.test_id, now),
                )
                claimed.append(claimed_run)
        return claimed
