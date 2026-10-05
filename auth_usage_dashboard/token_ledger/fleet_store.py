# Copyright (c) 2026 PitchAI. All rights reserved.
"""Master fleet store: idempotent ingest of node rows plus node freshness.

Rows carry absolute hourly values per node, so a re-sent or retried batch
simply overwrites the same keys. The node identity always comes from the
caller (a forced-command ssh key pins it), never from the payload.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import IO, TYPE_CHECKING, cast

from .node_store import LANE_COLUMNS_SQL, ROW_KEY, ROW_VALUES

if TYPE_CHECKING:
    from auth_usage_dashboard.timeseries_types import JsonObject, JsonValue, SqlValue

DEFAULT_FLEET_DB = Path("/srv/codex-usage-dashboard/token-ledger.sqlite3")
SCHEMA_VERSION = 1
MAX_ROWS_PER_INGEST = 200_000
MAX_LINE_BYTES = 16 * 1024
_TOKEN_CEILING = 10**15
_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,200}$")
_NODE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

_SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS token_usage_hourly (
    hour_epoch INTEGER NOT NULL,
    node TEXT NOT NULL,
"""
    + LANE_COLUMNS_SQL
    + """    input INTEGER NOT NULL,
    cached_input INTEGER NOT NULL,
    output INTEGER NOT NULL,
    reasoning INTEGER NOT NULL,
    total INTEGER NOT NULL,
    requests INTEGER NOT NULL,
    received_at REAL NOT NULL,
    PRIMARY KEY (hour_epoch, node, cell, project, agent, provider, model, route)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ledger_nodes (
    node TEXT PRIMARY KEY,
    last_collect_at REAL,
    last_ingest_at REAL NOT NULL,
    exporter_version TEXT,
    backlog_bytes INTEGER,
    files_tracked INTEGER,
    homes INTEGER,
    rows_received INTEGER NOT NULL DEFAULT 0,
    lane_errors TEXT
);
"""
)
_UPSERT = (
    "INSERT OR REPLACE INTO token_usage_hourly (hour_epoch, node, cell, project, agent, provider, model, route, "
    "project_title, input, cached_input, output, reasoning, total, requests, received_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def connect_fleet(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open the fleet store; writers create it with private permissions.

    Returns:
        Open SQLite connection.
    """
    if read_only:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.executescript(_SCHEMA)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    path.chmod(0o600)
    return connection


def _integer(value: JsonValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < _TOKEN_CEILING:
        message = "invalid integer"
        raise ValueError(message)
    return value


def _text(value: JsonValue, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _TEXT.match(value):
        message = "invalid text"
        raise ValueError(message)
    return value


def _row_values(node: str, row: JsonObject, received_at: float) -> tuple[SqlValue, ...]:
    hour = _integer(row.get("hour_epoch"))
    if hour % 3600:
        message = "hour is not aligned"
        raise ValueError(message)
    keys = [_text(row.get(name)) for name in ROW_KEY[1:]]
    values = [_integer(row.get(name)) for name in ROW_VALUES]
    return (hour, node, *keys, _text(row.get("project_title"), optional=True), *values, received_at)


def _record(line: str) -> JsonObject:
    record = cast("JsonValue", json.loads(line))
    if isinstance(record, dict):
        return record
    message = "record is not an object"
    raise ValueError(message)


def ingest(connection: sqlite3.Connection, node: str, stream: IO[str]) -> JsonObject:
    """Upsert one NDJSON batch (header line, then rows) for ``node``.

    Returns:
        Acknowledgement with the highest change sequence stored.

    Raises:
        ValueError: On an invalid node, oversized or malformed batch; nothing is stored.
    """
    if not _NODE.match(node):
        message = "invalid node name"
        raise ValueError(message)
    header: JsonObject = {}
    rows: list[tuple[SqlValue, ...]] = []
    acked = 0
    received_at = time.time()
    for number, line in enumerate(stream):
        if len(line) > MAX_LINE_BYTES or number > MAX_ROWS_PER_INGEST:
            message = "batch too large"
            raise ValueError(message)
        record = _record(line)
        if record.get("kind") == "header":
            header = record
            continue
        rows.append(_row_values(node, record, received_at))
        acked = max(acked, _integer(record.get("change_seq")))
    status = (
        node,
        _optional_number(header.get("collected_at")),
        received_at,
        _text(header.get("version"), optional=True),
        _optional_number(header.get("backlog_bytes")),
        _optional_number(header.get("files_tracked")),
        _optional_number(header.get("homes")),
        len(rows),
        _text(header.get("lane_errors") or None, optional=True),
    )
    with connection:
        connection.executemany(_UPSERT, rows)
        connection.execute(
            """INSERT INTO ledger_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node) DO UPDATE SET last_collect_at = excluded.last_collect_at,
                last_ingest_at = excluded.last_ingest_at, exporter_version = excluded.exporter_version,
                backlog_bytes = excluded.backlog_bytes, files_tracked = excluded.files_tracked,
                homes = excluded.homes, rows_received = ledger_nodes.rows_received + excluded.rows_received,
                lane_errors = excluded.lane_errors""",
            status,
        )
    return {"ok": True, "node": node, "rows": len(rows), "acked_seq": acked}


def _optional_number(value: JsonValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)
