# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define typed audit records and strict SQLite read boundaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypedDict

from .json_contract import decode_json

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from .json_contract import JsonObject, JsonValue
    from .models import AccountObservation, ResetCredit

type SqlValue = int | float | str | bytes | None


class AuditDataError(RuntimeError):
    """A persisted audit value violated the typed storage contract."""


class SqlRow(Protocol):
    """Expose typed values and column names from a SQLite result row."""

    def __getitem__(self, key: str | int, /) -> SqlValue:
        """Return one database value by column name or position."""
        raise NotImplementedError

    def keys(self) -> list[str]:
        """Return the available result-column names."""
        raise NotImplementedError


class SelectCursor(Protocol):
    """Expose the read operations used by the audit store."""

    def fetchone(self) -> SqlRow | None:
        """Return one row when the query produced one."""
        raise NotImplementedError

    def fetchall(self) -> list[SqlRow]:
        """Return every remaining query row."""
        raise NotImplementedError


class SelectConnection(Protocol):
    """Constrain SQLite access to typed scalar row values."""

    def execute(
        self,
        sql: str,
        parameters: tuple[SqlValue, ...] = (),
        /,
    ) -> SelectCursor:
        """Execute one read-only SQL statement."""
        raise NotImplementedError

    def commit(self) -> None:
        """Commit the current transaction."""
        raise NotImplementedError


class EventOptions(TypedDict, total=False):
    """Describe optional event columns accepted by ``record_event``."""

    severity: str
    account_ref: str | None
    account_label: str | None
    credit_ref: str | None
    expires_at: datetime | None
    threshold_hours: int | None
    attempt_id: str | None
    details: JsonObject | None


class WarningClaimOptions(TypedDict):
    """Describe one durable warning claim."""

    mode: str
    now: datetime
    account_ref: str
    credit: ResetCredit
    threshold_hours: int


class AttemptStartOptions(TypedDict):
    """Describe the identity and reason for one redemption attempt."""

    now: datetime
    observation: AccountObservation
    credit: ResetCredit
    reason: str


class AttemptUpdateOptions(TypedDict, total=False):
    """Describe optional redemption-attempt result columns."""

    outcome: str | None
    windows_reset: int | None
    verification: str | None
    error_code: str | None
    details: JsonObject | None


@dataclass(frozen=True, slots=True)
class RedemptionAttempt:
    """Identify a newly started or resumed durable redemption attempt."""

    attempt_id: str
    idempotency_key: str
    resumed: bool


@dataclass(frozen=True, slots=True)
class PendingAttempt:
    """Represent an unfinished redemption loaded for reconciliation."""

    attempt_id: str
    credit_ref: str
    expires_at: str
    status: str
    outcome: str | None
    windows_reset: int | None


def encode_json(value: JsonValue) -> str:
    """Encode one deterministic audit JSON value.

    Returns:
        The resulting text.

    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def select_connection(connection: sqlite3.Connection) -> SelectConnection:
    """Return SQLite through the typed read-result boundary."""
    typed_connection: SelectConnection = connection
    return typed_connection


def required_text(row: SqlRow, column: str) -> str:
    """Read a required text column and fail on audit corruption.

    Returns:
        The resulting text.

    Raises:
        AuditDataError: If persisted audit text violates the storage contract.

    """
    value = row[column]
    if not isinstance(value, str):
        msg = f"audit column {column} must contain text"
        raise AuditDataError(msg)
    return value


def optional_text(row: SqlRow, column: str) -> str | None:
    """Read an optional text column and fail on audit corruption.

    Returns:
        The resulting value.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    value = row[column]
    if value is None or isinstance(value, str):
        return value
    msg = f"audit column {column} must contain text or null"
    raise RuntimeError(msg)


def required_int(row: SqlRow, column: str) -> int:
    """Read a required integer column and fail on audit corruption.

    Returns:
        The computed value.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    value = row[column]
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = f"audit column {column} must contain an integer"
    raise RuntimeError(msg)


def optional_int(row: SqlRow, column: str) -> int | None:
    """Read an optional integer column and fail on audit corruption.

    Returns:
        The resulting value.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    value = row[column]
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    msg = f"audit column {column} must contain an integer or null"
    raise RuntimeError(msg)


def json_object(row: SqlRow, column: str) -> JsonObject:
    """Decode a required JSON object column and fail on audit corruption.

    Returns:
        The resulting value.

    Raises:
        AuditDataError: If persisted audit JSON violates the storage contract.

    """
    decoded = decode_json(required_text(row, column))
    if not isinstance(decoded, dict):
        msg = f"audit column {column} must contain a JSON object"
        raise AuditDataError(msg)
    return decoded


def summary_count(summary: JsonObject, name: str) -> int:
    """Read one required non-boolean run counter.

    Returns:
        The computed value.

    Raises:
        AuditDataError: If a persisted run counter violates the storage contract.

    """
    value = summary.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"guardian run summary field {name} must contain an integer"
        raise AuditDataError(msg)
    return value
