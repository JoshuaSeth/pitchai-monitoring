# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry fixture databases used by the monitoring health proof."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_TENANT_INSERT = "INSERT INTO tenants (id, name, created_at_ts, updated_at_ts) VALUES ('local', 'Local', 1, 1)"
_TEST_INSERT = (
    "INSERT INTO tests (id, tenant_id, name, base_url, enabled, definition_json, "
    "created_at_ts, updated_at_ts) "
)
_TEST_VALUES = "VALUES (?, 'local', ?, 'https://example.invalid/', ?, '{}', 1, 1)"
_RUN_INSERT = (
    "INSERT INTO runs (id, test_id, scheduled_for_ts, finished_at_ts, status) "
    "VALUES ('local.run', 'local.one', ?, ?, 'pass')"
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


REGISTRY_DATABASE = cast("RegistryDatabase", cast("object", import_module("e2e_registry.db")))


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


def retained_counts(db_path: Path) -> tuple[int, int, int, int]:
    """Return the retained schema version and inventory counts without writing."""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as connection:
        rows = [cast("tuple[object, ...] | None", connection.execute(query).fetchone()) for query in _RETAINED_QUERIES]
    counts = [0 if row is None else int(str(row[0])) for row in rows]
    return counts[0], counts[1], counts[2], counts[3]
