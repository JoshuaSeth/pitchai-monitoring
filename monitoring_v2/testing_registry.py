# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry fixture databases used by the monitoring health proof."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_TENANT_INSERT = "INSERT INTO tenants (id, name, created_at_ts, updated_at_ts) VALUES ('local', 'Local', 1, 1)"
_API_KEY_INSERT = "INSERT INTO api_keys (id, tenant_id, name, token_hash, created_at_ts) VALUES (?, 'local', ?, ?, 1)"
_TOKEN_BYTES = 24
_TEST_INSERT = (
    "INSERT INTO tests (id, tenant_id, name, base_url, enabled, definition_json, "
    "created_at_ts, updated_at_ts) "
)
_TEST_VALUES = "VALUES (?, 'local', ?, 'https://example.invalid/', ?, '{}', 1, 1)"
_RUN_INSERT = (
    "INSERT INTO runs (id, test_id, scheduled_for_ts, finished_at_ts, status) "
    "VALUES ('local.run', 'local.one', ?, ?, 'pass')"
)
# Fixture identity for the schedulable, parked and disabled status-scope rows.
SCOPE_ACTIVE_FAILING = "scope.active_failing"
SCOPE_ACTIVE_PASSING = "scope.active_passing"
SCOPE_RESUMED_PASSING = "scope.resumed_passing"
SCOPE_PARKED_FAILING = "scope.parked_failing"
SCOPE_DISABLED_FAILING = "scope.disabled_failing"
SCOPE_PARKED_REASON = "temporary probe cleanup"
SCOPE_DISABLED_REASON = "retired lane"
# Plaintext tenant credential seeded for the tenant-scoped status proof.
SCOPE_TENANT_TOKEN = secrets.token_urlsafe(_TOKEN_BYTES)
SCOPE_TENANT_KEY_ID = "local.scope_key"
# Production parks a lane for years and expires a pause by leaving it in the past.
SCOPE_PARKED_UNTIL_TS = 1_893_456_000.0
SCOPE_EXPIRED_UNTIL_TS = 1_600_000_000.0
_INTERVAL_SECONDS = 300
_RUN_AGE_SECONDS = 60.0
_PAUSE_TEST_INSERT = (
    "INSERT INTO tests (id, tenant_id, name, base_url, enabled, disabled_until_ts, disabled_reason,"
    " interval_seconds, definition_json, created_at_ts, updated_at_ts)"
    " VALUES (?, 'local', ?, 'https://example.invalid/', ?, ?, ?, ?, '{}', 1, 1)"
)
_STATE_INSERT = (
    "INSERT INTO test_state (test_id, effective_ok, fail_streak, success_streak) VALUES (?, ?, 0, 0)"
)
_SCOPE_RUN_INSERT = (
    "INSERT INTO runs (id, test_id, scheduled_for_ts, finished_at_ts, status) VALUES (?, ?, ?, ?, ?)"
)
# identifier, enabled, disabled_until_ts, disabled_reason, effective_ok
_SCOPE_ROWS: tuple[tuple[str, int, float | None, str | None, int], ...] = (
    (SCOPE_ACTIVE_FAILING, 1, None, None, 0),
    (SCOPE_ACTIVE_PASSING, 1, None, None, 1),
    (SCOPE_RESUMED_PASSING, 1, SCOPE_EXPIRED_UNTIL_TS, "pause expired", 1),
    (SCOPE_PARKED_FAILING, 1, SCOPE_PARKED_UNTIL_TS, SCOPE_PARKED_REASON, 0),
    (SCOPE_DISABLED_FAILING, 0, None, SCOPE_DISABLED_REASON, 0),
)
_RETAINED_QUERIES = (
    "SELECT v FROM schema_meta",
    "SELECT COUNT(*) FROM tests",
    "SELECT COUNT(*) FROM tests WHERE enabled=1",
    "SELECT COUNT(*) FROM runs",
)


class RegistrySettings(NamedTuple):
    """Settings accepted by the deployed registry schema initializer."""

    db_path: str


class RegistryDatabase(NamedTuple):
    """Deployed registry database module consumed through a typed boundary."""

    ensure_schema: Callable[[RegistrySettings], None]
    SCHEMA_VERSION: int


class RegistryAuth(NamedTuple):
    """Deployed registry auth module consumed through a typed boundary."""

    hash_token: Callable[[str], str]


REGISTRY_DATABASE = cast("RegistryDatabase", cast("object", import_module("e2e_registry.db")))
REGISTRY_AUTH = cast("RegistryAuth", cast("object", import_module("e2e_registry.auth")))


def registry_database(path: Path) -> Path:
    """Return the path of one isolated fixture database holding the deployed schema."""
    REGISTRY_DATABASE.ensure_schema(RegistrySettings(db_path=str(path)))
    return path


def seed_inventory(db_path: Path, *, now: float, run_age_seconds: float) -> None:
    """Register one enabled and one disabled test plus one finished run."""
    with closing(sqlite3.connect(str(db_path), timeout=30)) as connection:
        _ = connection.execute(_TENANT_INSERT)
        for identifier, enabled in (("local.one", 1), ("local.two", 0)):
            _ = connection.execute(_TEST_INSERT + _TEST_VALUES, (identifier, identifier, enabled))
        _ = connection.execute(_RUN_INSERT, (now - run_age_seconds, now - run_age_seconds))
        connection.commit()


def seed_status_scope_registry(db_path: Path, *, now: float) -> None:
    """Register active, resumed, parked and disabled rows plus one tenant key."""
    with closing(sqlite3.connect(str(db_path), timeout=30)) as connection:
        _ = connection.execute(_TENANT_INSERT)
        _ = connection.execute(
            _API_KEY_INSERT,
            (SCOPE_TENANT_KEY_ID, "scope", REGISTRY_AUTH.hash_token(SCOPE_TENANT_TOKEN)),
        )
        for identifier, enabled, until_ts, reason, effective_ok in _SCOPE_ROWS:
            _ = connection.execute(
                _PAUSE_TEST_INSERT,
                (identifier, identifier, enabled, until_ts, reason, _INTERVAL_SECONDS),
            )
            _ = connection.execute(_STATE_INSERT, (identifier, effective_ok))
            _ = connection.execute(
                _SCOPE_RUN_INSERT,
                (
                    f"{identifier}.run",
                    identifier,
                    now - _RUN_AGE_SECONDS,
                    now - _RUN_AGE_SECONDS,
                    "fail" if effective_ok == 0 else "pass",
                ),
            )
        connection.commit()


def retained_counts(db_path: Path) -> tuple[int, int, int, int]:
    """Return the retained schema version and inventory counts without writing."""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as connection:
        rows = [cast("tuple[object, ...] | None", connection.execute(query).fetchone()) for query in _RETAINED_QUERIES]
    counts = [0 if row is None else int(str(row[0])) for row in rows]
    return counts[0], counts[1], counts[2], counts[3]
