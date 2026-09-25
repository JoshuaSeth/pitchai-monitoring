# Copyright (c) 2026 PitchAI. All rights reserved.
"""Schema migrations for the E2E registry database."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from e2e_registry.db_core import (
    connect_database,
    fetch_all_rows,
    fetch_one_row,
    row_record,
)
from e2e_registry.models import require_integer, require_text

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Generator

    from e2e_registry.settings import RegistrySettings

SCHEMA_VERSION = 3
_SCHEMA_V2 = 2


def ensure_schema(settings: RegistrySettings) -> None:
    """Create or migrate the configured registry schema."""
    with registry_connection(settings):
        pass


@contextmanager
def registry_connection(
    settings: RegistrySettings,
) -> Generator[sqlite3.Connection, None, None]:
    """Yield a schema-ready registry connection and always close it.

    Yields:
        An open connection with the current registry schema.
    """
    connection = connect_database(settings.db_path)
    ensure_schema_connection(connection)
    try:
        yield connection
    finally:
        connection.close()


def ensure_schema_connection(connection: sqlite3.Connection) -> None:
    """Bring an open registry connection to the current schema version.

    Raises:
        RuntimeError: If no supported migration path reaches the current schema.
    """
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);",
    )
    row = fetch_one_row(
        connection.execute("SELECT v FROM schema_meta WHERE k='version'"),
    )
    current_version = require_integer(row_record(row).get("v"), label="schema version") if row is not None else 0
    if current_version >= SCHEMA_VERSION:
        return
    if current_version == 0:
        apply_v1(connection)
        apply_v2(connection)
        apply_v3(connection)
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta (k, v) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        return
    if current_version == 1:
        apply_v2(connection)
        apply_v3(connection)
        connection.execute(
            "UPDATE schema_meta SET v=? WHERE k='version'",
            (str(SCHEMA_VERSION),),
        )
        return
    if current_version == _SCHEMA_V2:
        apply_v3(connection)
        connection.execute(
            "UPDATE schema_meta SET v=? WHERE k='version'",
            (str(SCHEMA_VERSION),),
        )
        return
    message = f"Unsupported schema version upgrade path cur={current_version} target={SCHEMA_VERSION}"
    raise RuntimeError(message)


def column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """Return whether a table contains a named column."""
    rows = fetch_all_rows(
        connection.execute("SELECT name FROM pragma_table_info(?)", (table,)),
    )
    records = [row_record(row) for row in rows]
    return any(require_text(record.get("name"), label="column name") == column for record in records)


def apply_v1(connection: sqlite3.Connection) -> None:
    """Create the initial tenant, test, state, and run schema."""
    statements = (
        """
        CREATE TABLE IF NOT EXISTS tenants (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          created_at_ts REAL NOT NULL,
          updated_at_ts REAL NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS api_keys (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          token_hash TEXT NOT NULL,
          created_at_ts REAL NOT NULL,
          revoked_at_ts REAL,
          UNIQUE(token_hash)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tests (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          base_url TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          disabled_reason TEXT,
          disabled_until_ts REAL,
          interval_seconds INTEGER NOT NULL DEFAULT 300,
          timeout_seconds INTEGER NOT NULL DEFAULT 45,
          jitter_seconds INTEGER NOT NULL DEFAULT 30,
          down_after_failures INTEGER NOT NULL DEFAULT 2,
          up_after_successes INTEGER NOT NULL DEFAULT 2,
          notify_on_recovery INTEGER NOT NULL DEFAULT 0,
          dispatch_on_failure INTEGER NOT NULL DEFAULT 0,
          definition_json TEXT NOT NULL,
          created_at_ts REAL NOT NULL,
          updated_at_ts REAL NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS test_state (
          test_id TEXT PRIMARY KEY REFERENCES tests(id) ON DELETE CASCADE,
          effective_ok INTEGER NOT NULL DEFAULT 1,
          fail_streak INTEGER NOT NULL DEFAULT 0,
          success_streak INTEGER NOT NULL DEFAULT 0,
          last_ok_ts REAL,
          last_fail_ts REAL,
          last_infra_ts REAL,
          last_alert_ts REAL,
          next_due_ts REAL,
          running_lock_id TEXT,
          running_locked_at_ts REAL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY,
          test_id TEXT NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
          scheduled_for_ts REAL NOT NULL,
          started_at_ts REAL,
          finished_at_ts REAL,
          status TEXT NOT NULL,
          elapsed_ms REAL,
          error_kind TEXT,
          error_message TEXT,
          final_url TEXT,
          title TEXT,
          artifacts_json TEXT NOT NULL DEFAULT '{}'
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_tests_tenant_enabled ON tests(tenant_id, enabled);",
        "CREATE INDEX IF NOT EXISTS idx_test_state_due ON test_state(next_due_ts);",
        "CREATE INDEX IF NOT EXISTS idx_runs_test_started ON runs(test_id, started_at_ts DESC);",
    )
    for statement in statements:
        connection.execute(statement)


def apply_v2(connection: sqlite3.Connection) -> None:
    """Add uploaded code-test metadata.

    Raises:
        RuntimeError: If the migration declares an unsupported column.
    """
    columns = (
        ("test_kind", "TEXT NOT NULL DEFAULT 'stepflow'"),
        ("source_relpath", "TEXT"),
        ("source_filename", "TEXT"),
        ("source_sha256", "TEXT"),
        ("source_content_type", "TEXT"),
    )
    for column, declaration in columns:
        if column_exists(connection, "tests", column):
            continue
        if column == "test_kind":
            connection.execute(
                "ALTER TABLE tests ADD COLUMN test_kind TEXT NOT NULL DEFAULT 'stepflow';",
            )
        elif column == "source_relpath":
            connection.execute("ALTER TABLE tests ADD COLUMN source_relpath TEXT;")
        elif column == "source_filename":
            connection.execute("ALTER TABLE tests ADD COLUMN source_filename TEXT;")
        elif column == "source_sha256":
            connection.execute("ALTER TABLE tests ADD COLUMN source_sha256 TEXT;")
        elif column == "source_content_type":
            connection.execute("ALTER TABLE tests ADD COLUMN source_content_type TEXT;")
        else:
            message = f"Unsupported schema column {column} {declaration}"
            raise RuntimeError(message)


def apply_v3(connection: sqlite3.Connection) -> None:
    """Add persisted dispatcher-triage conclusions."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dispatch_runs (
          id TEXT PRIMARY KEY,
          created_at_ts REAL NOT NULL,
          state_key TEXT NOT NULL,
          bundle TEXT,
          ui_url TEXT,
          queue_state TEXT,
          agent_message TEXT,
          error_message TEXT,
          context_json TEXT NOT NULL DEFAULT '{}'
        );
        """,
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_dispatch_runs_created_at ON dispatch_runs(created_at_ts DESC);",
    )
