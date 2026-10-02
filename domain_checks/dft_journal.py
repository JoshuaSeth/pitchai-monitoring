# Copyright (c) 2026 PitchAI. All rights reserved.
"""Atomic local incident and retry state, containing no access-log content."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from itertools import starmap
from typing import TYPE_CHECKING, Literal, cast

from .dft_journal_storage import open_private_journal
from .dft_retention_consumer import RetentionIncident, observe_incident
from .dft_segment_io import SegmentCount, SegmentSnapshot

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from .dft_retention_consumer import CheckerObservation

_RECEIPT = re.compile(r"[A-Za-z0-9_.:-]{1,160}")
_MAX_PENDING = 1000
_MAX_BACKOFF = 300
_MAX_EXPONENT = 6
type Phase = Literal["failed", "recovered"]
type IncidentRow = tuple[str, float, float | None, int]


@dataclass(frozen=True)
class PendingTransition:
    """The immutable bytes and dedupe id must be identical on every retry."""

    delivery_id: str
    payload: str


class DftJournal:
    """One consumer-owned file; unrelated monitoring/retention data is untouched."""

    def __init__(self, path: Path) -> None:
        """Open the admitted consumer state file and initialize only its tables."""
        self.connection: sqlite3.Connection = open_private_journal(path, """
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY, opened REAL NOT NULL, closed REAL, acknowledged INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS current_incident (singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT);
            CREATE TABLE IF NOT EXISTS outbox (
                delivery_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL, receiver_id TEXT
            );
            CREATE TABLE IF NOT EXISTS segment_metadata (
                name TEXT PRIMARY KEY, device INTEGER NOT NULL, inode INTEGER NOT NULL, size INTEGER NOT NULL,
                byte_offset INTEGER NOT NULL, covered_start REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS segment_counts (
                name TEXT NOT NULL, timestamp REAL NOT NULL, total INTEGER NOT NULL,
                server_errors INTEGER NOT NULL, gateway_errors INTEGER NOT NULL, client_errors INTEGER NOT NULL,
                PRIMARY KEY(name,timestamp)
            );
        """)

    def close(self) -> None:
        """Release the connection without discarding any incident or retry state."""
        if self.connection.in_transaction:
            self.connection.rollback()
        self.connection.close()

    def load_segments(self) -> dict[str, SegmentSnapshot]:
        """Restore original-file metadata across process restarts.

        Returns:
            Content-free identities for the last successfully validated window.
        """
        rows = cast("list[tuple[str, int, int, int, int, float]]",
                    self.connection.execute("SELECT * FROM segment_metadata").fetchall())
        result: dict[str, SegmentSnapshot] = {}
        for row in rows:
            counters = cast("list[tuple[float, int, int, int, int]]", self.connection.execute(
                "SELECT timestamp,total,server_errors,gateway_errors,client_errors FROM segment_counts WHERE name=?",
                (row[0],),
            ).fetchall())
            restored_counts = tuple(starmap(SegmentCount, counters))
            result[row[0]] = SegmentSnapshot(*row[1:], counts=restored_counts)
        return result

    def save_segments(self, snapshots: dict[str, SegmentSnapshot]) -> None:
        """Atomically replace only consumer metadata, never original log files."""
        with self.connection:
            self.connection.execute("DELETE FROM segment_metadata")
            self.connection.execute("DELETE FROM segment_counts")
            for name, item in snapshots.items():
                self.connection.execute("INSERT INTO segment_metadata VALUES(?,?,?,?,?,?)",
                                        (name, item.device, item.inode, item.size, item.offset, item.covered_start))
                self.connection.executemany("INSERT INTO segment_counts VALUES(?,?,?,?,?,?)", [
                    (name, count.timestamp, count.total, count.server_errors, count.gateway_errors, count.client_errors)
                    for count in item.counts
                ])

    def current(self) -> RetentionIncident | None:
        """Read the exact retained identity, including its acknowledgement.

        Returns:
            The most recent incident, or None before the first failure.
        """
        row = cast("IncidentRow | None", self.connection.execute(
            "SELECT i.id, i.opened, i.closed, i.acknowledged FROM incidents i "
            "JOIN current_incident c ON c.id=i.id WHERE c.singleton=1",
        ).fetchone())
        return RetentionIncident(row[0], row[1], row[2], bool(row[3])) if row else None

    def record(
        self, observation: CheckerObservation, *, now: float, acknowledged_incident_id: str | None = None,
    ) -> RetentionIncident | None:
        """Commit the incident and its immutable outgoing intent atomically.

        Returns:
            The retained incident; a warning never replaces its identity.
        """
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.current()
            current = observe_incident(previous, observation, now=now, next_incident_id=str(uuid.uuid4()),
                                       owner_acknowledged_incident_id=acknowledged_incident_id)
            if current is not None:
                self._save_incident(current)
                if previous is None or previous.incident_id != current.incident_id:
                    self._enqueue(current, "failed", observation, now)
                elif previous.closed_at is None and current.closed_at is not None:
                    self._enqueue(current, "recovered", observation, now)
            return current

    def _save_incident(self, incident: RetentionIncident) -> None:
        self.connection.execute(
            "INSERT INTO incidents VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "closed=excluded.closed, acknowledged=excluded.acknowledged",
            (incident.incident_id, incident.opened_at, incident.closed_at, int(incident.acknowledged_by_owner)),
        )
        self.connection.execute(
            "INSERT INTO current_incident VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET id=excluded.id",
            (incident.incident_id,),
        )

    def _enqueue(self, incident: RetentionIncident, phase: Phase, observation: CheckerObservation, now: float) -> None:
        pending = cast("tuple[int]", self.connection.execute(
            "SELECT COUNT(*) FROM outbox WHERE receiver_id IS NULL",
        ).fetchone())[0]
        if pending >= _MAX_PENDING:
            message = "dft_outbox_capacity_exceeded"
            raise RuntimeError(message)
        delivery_id = f"dft-retention:{incident.incident_id}:{phase}"
        payload = json.dumps({
            "schema_version": 1, "delivery_id": delivery_id, "incident_id": incident.incident_id,
            "scope": "dft_web_access_retention", "phase": phase, "occurred_at": now,
            "observation": asdict(observation),
        }, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.connection.execute("INSERT INTO outbox(delivery_id,payload,created,next_attempt) VALUES(?,?,?,?)",
                                (delivery_id, payload, now, now))

    def pending(self, *, now: float) -> PendingTransition | None:
        """Return only the oldest unaccepted item when due, preserving ordering.

        Returns:
            The stable original transition; newer recovery cannot overtake it.
        """
        row = cast("tuple[str, str, float] | None", self.connection.execute(
            "SELECT delivery_id,payload,next_attempt FROM outbox WHERE receiver_id IS NULL ORDER BY rowid LIMIT 1",
        ).fetchone())
        if row is None or row[2] > now:
            return None
        return PendingTransition(row[0], row[1])

    def settle(self, delivery_id: str, *, receiver_id: str | None, now: float) -> None:
        """Accept an exact receipt or retain uncertain delivery for bounded retry.

        Raises:
            ValueError: A caller supplies a non-sanitized receipt identifier.
        """
        if receiver_id is not None and _RECEIPT.fullmatch(receiver_id) is None:
            message = "invalid_receiver_receipt"
            raise ValueError(message)
        with self.connection:
            row = cast("tuple[int] | None", self.connection.execute(
                "SELECT attempts FROM outbox WHERE delivery_id=? AND receiver_id IS NULL", (delivery_id,),
            ).fetchone())
            if row is None:
                return
            attempts = row[0] + 1
            delay = min(_MAX_BACKOFF, 5 << min(attempts - 1, _MAX_EXPONENT))
            self.connection.execute("UPDATE outbox SET receiver_id=?,attempts=?,next_attempt=? WHERE delivery_id=?",
                                    (receiver_id, attempts, now + delay, delivery_id))
