# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed SQLite write procedures for complete usage-history batches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .timeseries_rows import carry_last_known, fallback_account_ref, sample_row
from .timeseries_schema import INSERT_BATCH_IF_NEW_SQL, INSERT_BATCH_SQL, INSERT_SAMPLE_SQL

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from .timeseries_types import JsonObject, SqlRow, SqlValue


@dataclass(frozen=True)
class PendingBatch:
    """One complete inventory snapshot awaiting a transaction."""

    accounts: list[JsonObject]
    references: dict[str, str]
    sampled_at: datetime


@dataclass(frozen=True)
class BatchHeader:
    """Collection-batch identity persisted before its account rows."""

    sampled_at: str
    source: str
    account_count: int


def insert_accounts(
    connection: sqlite3.Connection,
    batch_id: int,
    pending: PendingBatch,
    collector_version: str,
) -> int:
    """Insert every account row in one pending batch.

    Returns:
        Number of inserted account rows.
    """
    inserted = 0
    for account in pending.accounts:
        label_value = account.get("label")
        label = label_value if isinstance(label_value, str) and label_value else "Unlabeled account"
        account_ref = pending.references.get(label, fallback_account_ref(label))
        row = sample_row(
            account,
            account_ref=account_ref,
            sampled_at=pending.sampled_at,
            collector_version=collector_version,
        )
        previous = _previous_sample(connection, account_ref)
        insert_sample(connection, batch_id, carry_last_known(row, previous))
        inserted += 1
    return inserted


def insert_sample(connection: sqlite3.Connection, batch_id: int, row: SqlRow) -> None:
    """Insert one typed secret-free account sample."""
    values = dict(row)
    values["batch_id"] = batch_id
    connection.execute(INSERT_SAMPLE_SQL, values)


def insert_batch(
    connection: sqlite3.Connection,
    header: BatchHeader,
    collector_version: str,
    *,
    ignore_existing: bool = False,
) -> int | None:
    """Insert one batch header and return its identifier when newly created.

    Returns:
        New batch identifier, or None when an ignored duplicate exists.

    Raises:
        RuntimeError: If SQLite does not return the new batch identifier.
    """
    command = INSERT_BATCH_IF_NEW_SQL if ignore_existing else INSERT_BATCH_SQL
    cursor = connection.execute(
        command,
        (header.sampled_at, header.source, collector_version, header.account_count),
    )
    if cursor.rowcount != 1:
        return None
    row_id = cursor.lastrowid
    if row_id is None:
        message = "inserted time-series batch lacks an identifier"
        raise RuntimeError(message)
    return row_id


def _previous_sample(connection: sqlite3.Connection, account_ref: str) -> SqlRow | None:
    row = cast(
        "sqlite3.Row | None",
        connection.execute(
            """SELECT * FROM account_usage_samples
               WHERE account_ref = ? ORDER BY sampled_at DESC, sample_id DESC LIMIT 1""",
            (account_ref,),
        ).fetchone(),
    )
    if row is None:
        return None
    previous: SqlRow = {}
    keys = row.keys()
    for key in keys:
        value = cast("SqlValue", row[key])
        previous[key] = value
    return previous
