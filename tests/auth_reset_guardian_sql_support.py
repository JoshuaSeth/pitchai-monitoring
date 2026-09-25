# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide strict SQLite result helpers for guardian behavior tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from auth_reset_guardian.audit_types import select_connection
from tests.auth_test_contract import FixtureContractError

if TYPE_CHECKING:
    import sqlite3

    from auth_reset_guardian.audit_types import (
        SelectCursor,
        SqlRow,
    )


def required_row(cursor: SelectCursor) -> SqlRow:
    """Require a query to return one row.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If the fixture query returns no row.

    """
    row = cursor.fetchone()
    if row is None:
        msg = "test query unexpectedly returned no rows"
        raise FixtureContractError(msg)
    return row


def row_int(row: SqlRow, index: int) -> int:
    """Require an integer SQLite result column.

    Returns:
        The computed value.

    Raises:
        FixtureContractError: If the fixture column is not an integer.

    """
    value = row[index]
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"SQLite column {index} must contain an integer"
        raise FixtureContractError(msg)
    return value


def row_text(row: SqlRow, index: int) -> str:
    """Require a text SQLite result column.

    Returns:
        The resulting text.

    Raises:
        FixtureContractError: If the fixture column is not text.

    """
    value = row[index]
    if not isinstance(value, str):
        msg = f"SQLite column {index} must contain text"
        raise FixtureContractError(msg)
    return value


def count_rows(connection: sqlite3.Connection, sql: str) -> int:
    """Return one required count result."""
    cursor = select_connection(connection).execute(sql)
    return row_int(required_row(cursor), 0)
