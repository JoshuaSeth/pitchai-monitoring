# Copyright (c) 2026 PitchAI. All rights reserved.
"""Node-local ledger: rollout cursors and hourly token rows.

A file's cursor advance and the hourly increments it produced commit in one
transaction, so every request is counted exactly once even when a run is
killed. Each changed row gets a new ``change_seq`` for incremental delivery.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

from .rollout import FileState

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from types import TracebackType

    from .json_types import SqlValue

DEFAULT_STATE = Path("/var/lib/pitchai-token-ledger/ledger.sqlite3")
ROW_KEY = ("hour_epoch", "cell", "project", "agent", "provider", "model", "route")
ROW_VALUES = ("input", "cached_input", "output", "reasoning", "total", "requests")
# Lane and label columns shared verbatim by the node and fleet ``CREATE TABLE`` statements.
LANE_COLUMNS_SQL = "".join(f"    {name} TEXT NOT NULL,\n" for name in ROW_KEY[1:]) + "    project_title TEXT,\n"

_SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS file_cursors (
    path TEXT PRIMARY KEY,
    inode INTEGER NOT NULL,
    offset INTEGER NOT NULL,
    route TEXT NOT NULL,
    thread_id TEXT,
    cwd TEXT,
    model TEXT,
    last_total TEXT,
    count_from REAL NOT NULL,
    baseline_pending INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS hourly (
    hour_epoch INTEGER NOT NULL,
"""
    + LANE_COLUMNS_SQL
    + """    input INTEGER NOT NULL DEFAULT 0,
    cached_input INTEGER NOT NULL DEFAULT 0,
    output INTEGER NOT NULL DEFAULT 0,
    reasoning INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    change_seq INTEGER NOT NULL,
    PRIMARY KEY (hour_epoch, cell, project, agent, provider, model, route)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS hourly_change_seq ON hourly(change_seq);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
)
_UPSERT = """
INSERT INTO hourly (hour_epoch, cell, project, agent, provider, model, route, project_title,
    input, cached_input, output, reasoning, total, requests, change_seq)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (hour_epoch, cell, project, agent, provider, model, route) DO UPDATE SET
    project_title = coalesce(excluded.project_title, hourly.project_title),
    input = hourly.input + excluded.input,
    cached_input = hourly.cached_input + excluded.cached_input,
    output = hourly.output + excluded.output,
    reasoning = hourly.reasoning + excluded.reasoning,
    total = hourly.total + excluded.total,
    requests = hourly.requests + excluded.requests,
    change_seq = excluded.change_seq
"""

_ROW_COLUMNS = (*ROW_KEY, "project_title", *ROW_VALUES, "change_seq")
_ROWS_SINCE = (
    "select hour_epoch, cell, project, agent, provider, model, route, project_title, input, cached_input, output, "
    "reasoning, total, requests, change_seq from hourly where change_seq > ? order by change_seq limit ?"
)
_SELECT_CURSORS = (
    "select path, inode, offset, route, thread_id, cwd, model, last_total, count_from, baseline_pending "
    "from file_cursors"
)
_CursorRow = tuple[str, int, int, str, "str | None", "str | None", "str | None", "str | None", float, int]

RowKey = tuple[int, str, str, str, str, str, str]
RowValues = tuple["str | None", list[int]]


class FileCursor(NamedTuple):
    """One rollout file's identity, runtime route and resume state."""

    path: str
    inode: int
    route: str
    state: FileState


class NodeStore:
    """Small WAL SQLite store owned by the host exporter."""

    connection: sqlite3.Connection

    def __init__(self, path: Path = DEFAULT_STATE) -> None:
        """Open (and create) the node ledger with a private directory."""
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30.0, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.executescript(_SCHEMA)
        path.chmod(0o600)

    def close(self) -> None:
        """Close the database connection."""
        self.connection.close()

    def meta(self, key: str, default: str = "") -> str:
        """Return one metadata value."""
        cursor = self.connection.execute("select value from meta where key = ?", (key,))
        row = cast("tuple[str] | None", cursor.fetchone())
        return str(row[0]) if row else default

    def set_meta(self, values: Mapping[str, str | float]) -> None:
        """Persist metadata values atomically."""
        with self._transaction():
            self.connection.executemany(
                "insert into meta(key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                [(key, str(value)) for key, value in values.items()],
            )

    def cursors(self) -> dict[str, tuple[int, str, FileState]]:
        """Return every known cursor keyed by path as (inode, route, state)."""
        found: dict[str, tuple[int, str, FileState]] = {}
        stored = cast("Iterator[_CursorRow]", self.connection.execute(_SELECT_CURSORS))
        for path, inode, offset, route, thread, cwd, model, total, count_from, pending in stored:
            last_total = tuple(cast("list[int]", json.loads(total))) if total else None
            state = FileState(int(offset), thread, cwd, model, last_total, float(count_from), bool(pending))
            found[str(path)] = (int(inode), str(route), state)
        return found

    def commit_file(self, cursor: FileCursor, rows: dict[RowKey, RowValues]) -> None:
        """Atomically store a file cursor and the hourly increments it produced."""
        state = cursor.state
        with self._transaction():
            sequence = self._next_sequence() if rows else 0
            self.connection.execute(
                "insert or replace into file_cursors values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cursor.path,
                    cursor.inode,
                    state.offset,
                    cursor.route,
                    state.thread_id,
                    state.cwd,
                    state.model,
                    json.dumps(list(state.last_total)) if state.last_total is not None else None,
                    state.count_from,
                    int(state.baseline_pending),
                    time.time(),
                ),
            )
            self.connection.executemany(
                _UPSERT,
                [(*key, title, *values, sequence) for key, (title, values) in rows.items()],
            )

    def forget_stale(self, present: Iterable[str], *, older_than: float) -> int:
        """Drop cursors of vanished rollouts that have not advanced since ``older_than``.

        Recently active cursors are kept even while their file is missing, so a
        rollout that is offloaded and restored is never counted twice.

        Returns:
            Number of cursors removed.
        """
        keep = set(present)
        cursor = self.connection.execute("select path from file_cursors where updated_at < ?", (older_than,))
        rows = cast("list[tuple[str]]", cursor.fetchall())
        paths = [row[0] for row in rows]
        stale = [path for path in paths if path not in keep]
        with self._transaction():
            self.connection.executemany("delete from file_cursors where path = ?", [(path,) for path in stale])
        return len(stale)

    def rows_since(self, sequence: int, limit: int) -> Iterator[dict[str, SqlValue]]:
        """Yield changed hourly rows after ``sequence`` in change order."""
        cursor = cast("Iterator[tuple[SqlValue, ...]]", self.connection.execute(_ROWS_SINCE, (sequence, limit)))
        for row in cursor:
            yield dict(zip(_ROW_COLUMNS, row, strict=True))

    def _next_sequence(self) -> int:
        value = int(self.meta("change_seq", "0")) + 1
        self.connection.execute(
            "insert into meta(key, value) values ('change_seq', ?) "
            "on conflict(key) do update set value = excluded.value",
            (str(value),),
        )
        return value

    def _transaction(self) -> _Transaction:
        return _Transaction(self.connection)


class _Transaction:
    """Immediate transaction context for an autocommit connection."""

    _connection: sqlite3.Connection

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")

    def __exit__(
        self,
        kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._connection.execute("COMMIT" if kind is None else "ROLLBACK")
