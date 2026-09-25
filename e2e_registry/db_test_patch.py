# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validated partial updates for registered E2E tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.db_core import utc_timestamp
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import dump_json, require_json_object

if TYPE_CHECKING:
    import sqlite3

    from e2e_registry.models import JsonObject
    from e2e_registry.settings import RegistrySettings


def _update_text_fields(
    connection: sqlite3.Connection,
    test_id: str,
    tenant_id: str,
    patch: JsonObject,
) -> bool:
    updated = False
    name = patch.get("name")
    if isinstance(name, str):
        connection.execute(
            "UPDATE tests SET name=? WHERE id=? AND tenant_id=?",
            (name.strip(), test_id, tenant_id),
        )
        updated = True
    base_url = patch.get("base_url")
    if isinstance(base_url, str):
        connection.execute(
            "UPDATE tests SET base_url=? WHERE id=? AND tenant_id=?",
            (base_url.strip(), test_id, tenant_id),
        )
        updated = True
    return updated


def _update_schedule_fields(
    connection: sqlite3.Connection,
    test_id: str,
    tenant_id: str,
    patch: JsonObject,
) -> bool:
    updated = False
    interval = patch.get("interval_seconds")
    if isinstance(interval, int) and not isinstance(interval, bool):
        connection.execute(
            "UPDATE tests SET interval_seconds=? WHERE id=? AND tenant_id=?",
            (interval, test_id, tenant_id),
        )
        updated = True
    timeout = patch.get("timeout_seconds")
    if isinstance(timeout, int) and not isinstance(timeout, bool):
        connection.execute(
            "UPDATE tests SET timeout_seconds=? WHERE id=? AND tenant_id=?",
            (timeout, test_id, tenant_id),
        )
        updated = True
    jitter = patch.get("jitter_seconds")
    if isinstance(jitter, int) and not isinstance(jitter, bool):
        connection.execute(
            "UPDATE tests SET jitter_seconds=? WHERE id=? AND tenant_id=?",
            (jitter, test_id, tenant_id),
        )
        updated = True
    return updated


def _update_threshold_fields(
    connection: sqlite3.Connection,
    test_id: str,
    tenant_id: str,
    patch: JsonObject,
) -> bool:
    updated = False
    down_after = patch.get("down_after_failures")
    if isinstance(down_after, int) and not isinstance(down_after, bool):
        connection.execute(
            "UPDATE tests SET down_after_failures=? WHERE id=? AND tenant_id=?",
            (down_after, test_id, tenant_id),
        )
        updated = True
    up_after = patch.get("up_after_successes")
    if isinstance(up_after, int) and not isinstance(up_after, bool):
        connection.execute(
            "UPDATE tests SET up_after_successes=? WHERE id=? AND tenant_id=?",
            (up_after, test_id, tenant_id),
        )
        updated = True
    return updated


def _update_notification_fields(
    connection: sqlite3.Connection,
    test_id: str,
    tenant_id: str,
    patch: JsonObject,
) -> bool:
    updated = False
    notify = patch.get("notify_on_recovery")
    if isinstance(notify, bool):
        connection.execute(
            "UPDATE tests SET notify_on_recovery=? WHERE id=? AND tenant_id=?",
            (int(notify), test_id, tenant_id),
        )
        updated = True
    dispatch = patch.get("dispatch_on_failure")
    if isinstance(dispatch, bool):
        connection.execute(
            "UPDATE tests SET dispatch_on_failure=? WHERE id=? AND tenant_id=?",
            (int(dispatch), test_id, tenant_id),
        )
        updated = True
    return updated


def _update_definition(
    connection: sqlite3.Connection,
    test_id: str,
    tenant_id: str,
    patch: JsonObject,
) -> bool:
    definition = patch.get("definition")
    if definition is None:
        return False
    validated = require_json_object(definition, label="definition")
    connection.execute(
        "UPDATE tests SET definition_json=? WHERE id=? AND tenant_id=?",
        (dump_json(validated), test_id, tenant_id),
    )
    return True


def patch_test(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
    patch: JsonObject,
) -> bool:
    """Apply supported fields from a validated partial test update.

    Returns:
        Whether the tenant-owned test was updated.
    """
    with registry_connection(settings) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE;")
            updates = (
                _update_text_fields(connection, test_id, tenant_id, patch),
                _update_schedule_fields(connection, test_id, tenant_id, patch),
                _update_threshold_fields(connection, test_id, tenant_id, patch),
                _update_notification_fields(connection, test_id, tenant_id, patch),
                _update_definition(connection, test_id, tenant_id, patch),
            )
            if not any(updates):
                return False
            result = connection.execute(
                "UPDATE tests SET updated_at_ts=? WHERE id=? AND tenant_id=?",
                (utc_timestamp(), test_id, tenant_id),
            )
        return result.rowcount > 0
