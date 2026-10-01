# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed records and row validation for organization redemption claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from .organization_policy import RedemptionSelection


@dataclass(frozen=True)
class ClaimRequest:
    """Exact identity and evidence key for one coordinated claim."""

    run_id: str
    now: datetime
    decision_key: str
    selection: RedemptionSelection


@dataclass(frozen=True)
class CoordinatedAttempt:
    """Durable provider attempt returned by the organization claim transaction."""

    attempt_id: str
    idempotency_key: str
    resumed: bool
    executable: bool
    status: str


def row_text(row: sqlite3.Row, key: str) -> str:
    """Read one required text column from an organization claim row.

    Returns:
        The validated text value.

    Raises:
        TypeError: The requested column is not text.
    """
    raw_value = cast("object", row[key])
    if not isinstance(raw_value, str):
        message = f"organization audit column {key} is not text"
        raise TypeError(message)
    return raw_value
