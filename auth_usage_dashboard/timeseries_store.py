# Copyright (c) 2026 PitchAI. All rights reserved.
"""Append-only SQLite writer for per-account Codex usage history."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final

from .timeseries_legacy import LEGACY_SOURCE, load_legacy_batches
from .timeseries_rows import SOURCE, account_references
from .timeseries_schema import connect_database, parse_timestamp, secure_database_files
from .timeseries_writer import BatchHeader, PendingBatch, insert_accounts, insert_batch, insert_sample

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from .timeseries_types import JsonObject

_LEGACY_MARKER = "legacy_json_v1_imported"
_MIN_SAMPLE_INTERVAL_SECONDS = 60
_MAX_COLLECTOR_VERSION_LENGTH = 120


@final
class UsageTimeSeriesStore:
    """Persist complete broker inventory snapshots without automatic pruning."""

    path: Path
    sample_interval_seconds: int
    collector_version: str
    legacy_json_path: Path | None

    def __init__(
        self,
        path: Path,
        *,
        sample_interval_seconds: int = 300,
        collector_version: str = "development",
        legacy_json_path: Path | None = None,
    ) -> None:
        """Initialize the durable store and apply idempotent schema migration.

        Raises:
            ValueError: If cadence or collector identity is invalid.
        """
        if sample_interval_seconds < _MIN_SAMPLE_INTERVAL_SECONDS:
            message = "time-series sample interval must be at least 60 seconds"
            raise ValueError(message)
        if not collector_version.strip():
            message = "collector version must not be empty"
            raise ValueError(message)
        self.path = path.expanduser().resolve()
        self.sample_interval_seconds = sample_interval_seconds
        self.collector_version = collector_version.strip()[:_MAX_COLLECTOR_VERSION_LENGTH]
        self.legacy_json_path = legacy_json_path.expanduser().resolve() if legacy_json_path is not None else None
        connection = connect_database(self.path)
        connection.close()

    def record(
        self,
        accounts: list[JsonObject],
        *,
        raw_accounts: list[JsonObject],
        at: datetime,
    ) -> bool:
        """Append one all-account batch when the five-minute boundary is due.

        Returns:
            True when a complete batch was appended; False when not yet due.

        """
        sampled_at = at.astimezone(UTC)
        pending = PendingBatch(
            accounts=accounts,
            references=account_references(raw_accounts),
            sampled_at=sampled_at,
        )
        connection = connect_database(self.path)
        try:
            return self._record_connection(connection, pending)
        finally:
            connection.close()
            secure_database_files(self.path)

    def is_due(self, at: datetime) -> bool:
        """Check whether a new batch is due at the supplied timestamp.

        Returns:
            True when no batch exists within the configured cadence.
        """
        with closing(connect_database(self.path, read_only=True)) as connection:
            return self._sample_due(connection, at.astimezone(UTC))

    def _record_connection(
        self,
        connection: sqlite3.Connection,
        pending: PendingBatch,
    ) -> bool:
        connection.execute("BEGIN IMMEDIATE")
        recorded = self._record_transaction(connection, pending)
        connection.commit()
        return recorded

    def _record_transaction(
        self,
        connection: sqlite3.Connection,
        pending: PendingBatch,
    ) -> bool:
        self._import_legacy(connection, pending.references)
        if not self._sample_due(connection, pending.sampled_at):
            return False
        header = BatchHeader(
            sampled_at=_isoformat(pending.sampled_at),
            source=SOURCE,
            account_count=len(pending.accounts),
        )
        batch_id = insert_batch(connection, header, self.collector_version)
        if batch_id is None:
            message = "time-series batch timestamp already exists"
            raise RuntimeError(message)
        inserted = insert_accounts(connection, batch_id, pending, self.collector_version)
        if inserted != len(pending.accounts):
            message = "time-series batch did not contain every account"
            raise RuntimeError(message)
        return True

    def _import_legacy(
        self,
        connection: sqlite3.Connection,
        references: dict[str, str],
    ) -> None:
        marker = cast(
            "sqlite3.Row | None",
            connection.execute(
                "SELECT 1 FROM store_metadata WHERE metadata_key = ?",
                (_LEGACY_MARKER,),
            ).fetchone(),
        )
        if marker is not None:
            return
        path = self.legacy_json_path
        if path is not None and path.is_file():
            batches = load_legacy_batches(
                path,
                references=references,
                collector_version=self.collector_version,
            )
            for sampled_at, rows in batches:
                header = BatchHeader(
                    sampled_at=sampled_at,
                    source=LEGACY_SOURCE,
                    account_count=len(rows),
                )
                batch_id = insert_batch(
                    connection,
                    header,
                    self.collector_version,
                    ignore_existing=True,
                )
                if batch_id is not None:
                    for row in rows:
                        insert_sample(connection, batch_id, row)
        connection.execute(
            "INSERT INTO store_metadata(metadata_key, metadata_value) VALUES (?, ?)",
            (_LEGACY_MARKER, _isoformat(datetime.now(UTC))),
        )

    def _sample_due(self, connection: sqlite3.Connection, sampled_at: datetime) -> bool:
        row = cast(
            "sqlite3.Row | None",
            connection.execute(
                """SELECT sampled_at, source, collector_version
                     FROM collection_batches
                    ORDER BY sampled_at DESC, batch_id DESC LIMIT 1""",
            ).fetchone(),
        )
        if row is None:
            return True
        source = cast("str", row["source"])
        collector_version = cast("str", row["collector_version"])
        if source != SOURCE or collector_version != self.collector_version:
            return True
        last_at = parse_timestamp(cast("str", row["sampled_at"]))
        return (sampled_at - last_at).total_seconds() >= self.sample_interval_seconds


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
