# Copyright (c) 2026 PitchAI. All rights reserved.
"""SQLite primitives shared by the E2E registry repositories."""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

from e2e_registry.models import DatabaseScalar, InvalidRegistryDataError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from e2e_registry.models import DatabaseRecord


def utc_timestamp() -> float:
    """Return the current Unix timestamp in UTC."""
    return time.time()


def new_uuid() -> str:
    """Return a new opaque registry identifier."""
    return str(uuid.uuid4())


def connect_database(path: str) -> sqlite3.Connection:
    """Open a configured registry database with strict connection settings.

    Args:
        path: Filesystem path to the SQLite database.

    Returns:
        An open SQLite connection using named rows.

    Raises:
        ValueError: If the path is empty.
    """
    normalized_path = path.strip()
    if not normalized_path:
        message = "Missing db_path"
        raise ValueError(message)
    Path(normalized_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        normalized_path,
        timeout=30,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA busy_timeout = 5000;")
    connection.execute("PRAGMA journal_mode = WAL;")
    return connection


type UntrustedDatabaseScalar = DatabaseScalar | bytearray | memoryview


def database_scalar(value: UntrustedDatabaseScalar, *, label: str) -> DatabaseScalar:
    """Validate a scalar returned from SQLite.

    Returns:
        The validated scalar.

    Raises:
        InvalidRegistryDataError: If SQLite returned an unsupported value type.
    """
    if value is None or isinstance(value, (str, int, float, bytes)):
        return value
    message = f"{label} has unsupported SQLite type {type(value).__name__}"
    raise InvalidRegistryDataError(message)


def row_record(row: sqlite3.Row) -> DatabaseRecord:
    """Convert a SQLite row to a concrete scalar mapping.

    Returns:
        A mapping with validated scalar values.
    """
    record: DatabaseRecord = {}
    keys = row.keys()
    for key in keys:
        raw_value = cast("UntrustedDatabaseScalar", row[key])
        record[key] = database_scalar(raw_value, label=key)
    return record


def rows_records(rows: Iterable[sqlite3.Row]) -> list[DatabaseRecord]:
    """Convert SQLite rows to concrete scalar mappings.

    Returns:
        Mappings with validated scalar values.
    """
    return [row_record(row) for row in rows]


def fetch_one_row(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    """Return one typed named row from a configured SQLite cursor.

    Returns:
        The next row, or ``None`` when the query has no result.
    """
    return cast("sqlite3.Row | None", cursor.fetchone())


def fetch_all_rows(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    """Return all typed named rows from a configured SQLite cursor.

    Returns:
        The remaining query rows.
    """
    return cast("list[sqlite3.Row]", cursor.fetchall())
