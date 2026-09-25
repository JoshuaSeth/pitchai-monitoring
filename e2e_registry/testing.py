# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit test checks compatible with the strict validation policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.db_core import fetch_one_row, row_record
from e2e_registry.db_schema import registry_connection

if TYPE_CHECKING:
    from e2e_registry.settings import RegistrySettings


def require_test_condition(*, condition: bool, message: str) -> None:
    """Fail a test unless its required condition is true.

    Args:
        condition: Test invariant to enforce.
        message: Failure detail shown to the developer.

    Raises:
        AssertionError: If the condition is false.
    """
    if not condition:
        raise AssertionError(message)


def registry_lock_owner(settings: RegistrySettings, test_id: str) -> str | None:
    """Read the current test lock owner for a persistence test.

    Returns:
        The active run identity, or ``None`` when the test is unlocked or absent.
    """
    with registry_connection(settings) as connection:
        row = fetch_one_row(
            connection.execute(
                "SELECT running_lock_id FROM test_state WHERE test_id=?",
                (test_id,),
            ),
        )
    if row is None:
        return None
    owner = row_record(row).get("running_lock_id")
    return str(owner) if owner is not None else None
