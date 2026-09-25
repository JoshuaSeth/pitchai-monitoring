# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed registry health summary queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.db_core import fetch_all_rows, rows_records
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import (
    InvalidRegistryDataError,
)

if TYPE_CHECKING:
    from e2e_registry.models import (
        DatabaseRecord,
        JsonObject,
        JsonValue,
    )
    from e2e_registry.settings import RegistrySettings

_MAX_STATUS_TESTS = 200


def _json_record(record: DatabaseRecord) -> JsonObject:
    output: JsonObject = {}
    for key, value in record.items():
        if isinstance(value, bytes):
            message = f"Registry status field {key} unexpectedly contains bytes"
            raise InvalidRegistryDataError(message)
        json_value: JsonValue = value
        output[key] = json_value
    return output


def status_summary(settings: RegistrySettings) -> JsonObject:
    """Return registry state while treating missing or malformed health as failing."""
    with registry_connection(settings) as connection:
        rows = fetch_all_rows(
            connection.execute(
                """
            SELECT
              t.id AS test_id,
              t.tenant_id AS tenant_id,
              t.name AS test_name,
              t.base_url AS base_url,
              t.test_kind AS test_kind,
              t.enabled AS enabled,
              s.effective_ok AS effective_ok,
              s.fail_streak AS fail_streak,
              s.success_streak AS success_streak,
              s.last_ok_ts AS last_ok_ts,
              s.last_fail_ts AS last_fail_ts,
              s.last_infra_ts AS last_infra_ts,
              s.next_due_ts AS next_due_ts,
              r.status AS last_status,
              r.elapsed_ms AS last_elapsed_ms,
              r.finished_at_ts AS last_finished_at_ts
            FROM tests t
            LEFT JOIN test_state s ON s.test_id=t.id
            LEFT JOIN runs r ON r.id = (
              SELECT r2.id FROM runs r2 WHERE r2.test_id=t.id ORDER BY r2.scheduled_for_ts DESC LIMIT 1
            )
            ORDER BY t.created_at_ts DESC
            """,
            ),
        )
        test_records = rows_records(rows)
        failing_count = sum(record.get("effective_ok") not in {1, "1"} for record in test_records)
        tests: list[JsonValue] = [_json_record(record) for record in test_records[:_MAX_STATUS_TESTS]]
        return {
            "ok": True,
            "total_tests": len(test_records),
            "failing_tests": failing_count,
            "tests": tests,
        }
