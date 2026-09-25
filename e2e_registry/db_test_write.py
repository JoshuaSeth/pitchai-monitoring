# Copyright (c) 2026 PitchAI. All rights reserved.
"""Create and lifecycle mutations for registered E2E tests."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, NamedTuple

from e2e_registry.db_core import new_uuid, utc_timestamp
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import dump_json

if TYPE_CHECKING:
    from e2e_registry.models import DatabaseRecord, JsonObject
    from e2e_registry.settings import RegistrySettings


class NewTest(NamedTuple):
    """Validated values needed to register a test."""

    tenant_id: str
    name: str
    base_url: str
    interval_seconds: int
    timeout_seconds: int
    jitter_seconds: int
    down_after_failures: int
    up_after_successes: int
    notify_on_recovery: bool
    dispatch_on_failure: bool
    test_id: str | None = None
    test_kind: str = "stepflow"
    definition: JsonObject | None = None
    source_relpath: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None
    source_content_type: str | None = None


class TestSourceUpdate(NamedTuple):
    """Stored-source pointer replacement for one code-based test."""

    tenant_id: str
    test_id: str
    source_relpath: str
    source_filename: str
    source_sha256: str | None
    source_content_type: str | None


class TestDisableChange(NamedTuple):
    """Requested enabled/disabled state for one test."""

    tenant_id: str
    test_id: str
    disabled: bool
    reason: str | None
    until_ts: float | None


def insert_test(settings: RegistrySettings, registration: NewTest) -> DatabaseRecord:
    """Persist a registered test and initial healthy state.

    Returns:
        The created test's public persistence fields.
    """
    now = utc_timestamp()
    test_id = registration.test_id.strip() if registration.test_id is not None else new_uuid()
    if not test_id:
        test_id = new_uuid()
    jitter_seconds = max(0, registration.jitter_seconds)
    jitter = secrets.randbelow(jitter_seconds + 1) if jitter_seconds else 0
    next_due = now + jitter
    test_kind = registration.test_kind.strip().lower() or "stepflow"
    definition = registration.definition if registration.definition is not None else {}
    source_relpath = registration.source_relpath.strip() if registration.source_relpath else None
    source_filename = registration.source_filename.strip() if registration.source_filename else None
    source_sha256 = registration.source_sha256.strip() if registration.source_sha256 else None
    source_content_type = registration.source_content_type.strip() if registration.source_content_type else None

    with registry_connection(settings) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE;")
            connection.execute(
                """
                INSERT INTO tests (
                  id, tenant_id, name, base_url, enabled, interval_seconds, timeout_seconds, jitter_seconds,
                  down_after_failures, up_after_successes, notify_on_recovery, dispatch_on_failure,
                  test_kind, definition_json, source_relpath, source_filename, source_sha256, source_content_type,
                  created_at_ts, updated_at_ts
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    test_id,
                    registration.tenant_id,
                    registration.name.strip(),
                    registration.base_url.strip(),
                    registration.interval_seconds,
                    registration.timeout_seconds,
                    registration.jitter_seconds,
                    registration.down_after_failures,
                    registration.up_after_successes,
                    int(registration.notify_on_recovery),
                    int(registration.dispatch_on_failure),
                    test_kind,
                    dump_json(definition),
                    source_relpath,
                    source_filename,
                    source_sha256,
                    source_content_type,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO test_state (
                  test_id, effective_ok, fail_streak, success_streak, last_ok_ts, last_fail_ts, last_infra_ts,
                  last_alert_ts, next_due_ts, running_lock_id, running_locked_at_ts
                ) VALUES (?, 1, 0, 0, NULL, NULL, NULL, NULL, ?, NULL, NULL)
                """,
                (test_id, next_due),
            )
        return {
            "id": test_id,
            "tenant_id": registration.tenant_id,
            "name": registration.name.strip(),
            "base_url": registration.base_url.strip(),
            "test_kind": test_kind,
            "source_relpath": source_relpath,
            "next_due_ts": next_due,
        }


def update_test_source(settings: RegistrySettings, update: TestSourceUpdate) -> bool:
    """Replace the stored source pointer for a tenant-owned test.

    Returns:
        Whether the tenant-owned test was updated.
    """
    with registry_connection(settings) as connection:
        result = connection.execute(
            """
            UPDATE tests
            SET source_relpath=?, source_filename=?, source_sha256=?, source_content_type=?, updated_at_ts=?
            WHERE id=? AND tenant_id=?
            """,
            (
                update.source_relpath.strip(),
                update.source_filename.strip(),
                update.source_sha256.strip() if update.source_sha256 else None,
                update.source_content_type.strip() if update.source_content_type else None,
                utc_timestamp(),
                update.test_id,
                update.tenant_id,
            ),
        )
        return result.rowcount > 0


def set_test_disabled(settings: RegistrySettings, change: TestDisableChange) -> bool:
    """Apply a permanent or temporary disabled state to a tenant-owned test.

    Returns:
        Whether the tenant-owned test was updated.
    """
    now = utc_timestamp()
    if change.disabled and change.until_ts is not None and change.until_ts > now:
        enabled = 1
        disabled_until = change.until_ts
    elif change.disabled:
        enabled = 0
        disabled_until = None
    else:
        enabled = 1
        disabled_until = None
    reason = change.reason.strip() if change.disabled and change.reason else None

    with registry_connection(settings) as connection:
        result = connection.execute(
            """
            UPDATE tests
            SET enabled=?, disabled_reason=?, disabled_until_ts=?, updated_at_ts=?
            WHERE id=? AND tenant_id=?
            """,
            (enabled, reason, disabled_until, now, change.test_id, change.tenant_id),
        )
        return result.rowcount > 0


def trigger_run_now(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
) -> bool:
    """Make one tenant-owned test immediately eligible for claiming.

    Returns:
        Whether the tenant-owned test was made due.
    """
    with registry_connection(settings) as connection:
        result = connection.execute(
            """
            UPDATE test_state
            SET next_due_ts=?
            WHERE test_id IN (SELECT id FROM tests WHERE id=? AND tenant_id=?)
            """,
            (utc_timestamp(), test_id, tenant_id),
        )
        return result.rowcount > 0
