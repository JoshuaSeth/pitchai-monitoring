# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict typed assertions shared by organization guardian tests."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Hashable
    from pathlib import Path


def database_rows(db_path: Path, statement: str) -> list[sqlite3.Row]:
    """Read typed rows from a test guardian database.

    Returns:
        All rows produced by the read-only statement.
    """
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return list(connection.execute(statement))


def row_integer(row: sqlite3.Row, key: str) -> int:
    """Read one required integer from a test database row.

    Returns:
        The validated integer.

    Raises:
        TypeError: The selected value is not an integer.
    """
    value = cast("object", row[key])
    if isinstance(value, bool) or not isinstance(value, int):
        message = f"test database column {key} is not an integer"
        raise TypeError(message)
    return value


def require(*, condition: bool, message: str) -> None:
    """Raise a test failure when a required condition is false.

    Raises:
        AssertionError: The condition is false.
    """
    if not condition:
        raise AssertionError(message)


def require_equal(actual: Hashable, expected: Hashable) -> None:
    """Raise a test failure when two values differ.

    Raises:
        AssertionError: The values are unequal.
    """
    if actual != expected:
        message = f"expected {expected!r}, received {actual!r}"
        raise AssertionError(message)
