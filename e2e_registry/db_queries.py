# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read-only query repositories for E2E tests and runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.db_core import fetch_all_rows, fetch_one_row, row_record, rows_records
from e2e_registry.db_schema import registry_connection

if TYPE_CHECKING:
    from e2e_registry.models import DatabaseRecord
    from e2e_registry.settings import RegistrySettings

_MAX_RUN_LIMIT = 500


def list_tests(settings: RegistrySettings, *, tenant_id: str) -> list[DatabaseRecord]:
    """Return all tests visible to a tenant, newest first."""
    with registry_connection(settings) as connection:
        rows = fetch_all_rows(
            connection.execute(
                """
            SELECT
              t.*,
              s.effective_ok, s.fail_streak, s.success_streak, s.last_ok_ts, s.last_fail_ts, s.last_infra_ts,
              s.last_alert_ts, s.next_due_ts
            FROM tests t
            LEFT JOIN test_state s ON s.test_id=t.id
            WHERE t.tenant_id=?
            ORDER BY t.created_at_ts DESC
            """,
                (tenant_id,),
            ),
        )
        return rows_records(rows)


def get_test(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
) -> DatabaseRecord | None:
    """Return one tenant-owned test and its current state."""
    with registry_connection(settings) as connection:
        row = fetch_one_row(
            connection.execute(
                """
            SELECT
              t.*,
              s.effective_ok, s.fail_streak, s.success_streak, s.last_ok_ts, s.last_fail_ts, s.last_infra_ts,
              s.last_alert_ts, s.next_due_ts
            FROM tests t
            LEFT JOIN test_state s ON s.test_id=t.id
            WHERE t.id=? AND t.tenant_id=?
            """,
                (test_id, tenant_id),
            ),
        )
        return row_record(row) if row is not None else None


def get_test_config_internal(
    settings: RegistrySettings,
    *,
    test_id: str,
) -> DatabaseRecord | None:
    """Return one test configuration for trusted internal callers."""
    with registry_connection(settings) as connection:
        row = fetch_one_row(
            connection.execute("SELECT * FROM tests WHERE id=?", (test_id,)),
        )
        return row_record(row) if row is not None else None


def list_runs(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
    limit: int = 50,
) -> list[DatabaseRecord]:
    """Return recent runs for one tenant-owned test."""
    bounded_limit = max(1, min(limit, _MAX_RUN_LIMIT))
    with registry_connection(settings) as connection:
        rows = fetch_all_rows(
            connection.execute(
                """
            SELECT r.*
            FROM runs r
            JOIN tests t ON t.id=r.test_id
            WHERE r.test_id=? AND t.tenant_id=?
            ORDER BY r.scheduled_for_ts DESC
            LIMIT ?
            """,
                (test_id, tenant_id, bounded_limit),
            ),
        )
        return rows_records(rows)


def get_run(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    run_id: str,
) -> DatabaseRecord | None:
    """Return one tenant-owned run with test metadata."""
    with registry_connection(settings) as connection:
        row = fetch_one_row(
            connection.execute(
                """
            SELECT r.*, t.tenant_id, t.name AS test_name, t.base_url AS test_base_url
            FROM runs r
            JOIN tests t ON t.id=r.test_id
            WHERE r.id=? AND t.tenant_id=?
            """,
                (run_id, tenant_id),
            ),
        )
        return row_record(row) if row is not None else None
