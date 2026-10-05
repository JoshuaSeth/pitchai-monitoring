# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-node freshness and backlog of the fleet token ledger."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

    from .json_types import JsonObject, JsonValue, SqlValue

NODE_STALE_SECONDS = 1_200


def node_coverage(connection: sqlite3.Connection, expected: tuple[str, ...], now: float) -> JsonObject:
    """Return per-node freshness and backfill backlog for the expected nodes."""
    query = "select node, last_ingest_at, last_collect_at, backlog_bytes from ledger_nodes"
    rows: dict[str, tuple[float | None, float | None, int]] = {}
    for node, last_ingest, last_collect, backlog in cast("Iterator[tuple[SqlValue, ...]]", connection.execute(query)):
        rows[str(node)] = (_number(last_ingest), _number(last_collect), int(backlog or 0))
    sources: list[JsonValue] = []
    stale_flags: list[bool] = []
    ingests: list[float] = []
    backlog_total = 0
    for node in sorted(set(expected) | set(rows)):
        last_ingest, last_collect, backlog = rows.get(node, (None, None, 0))
        if last_ingest is not None:
            ingests.append(last_ingest)
        backlog_total += backlog
        stale = last_ingest is None or now - last_ingest > NODE_STALE_SECONDS
        stale_flags.append(stale)
        sources.append(
            {
                "name": node,
                "label": node,
                "last_ingest_at": iso_utc(last_ingest) if last_ingest is not None else None,
                "last_collect_at": iso_utc(last_collect) if last_collect is not None else None,
                "backlog_bytes": backlog,
                "stale": stale,
            },
        )
    return {
        "sources": sources,
        "stale": any(stale_flags),
        "last_collected_at": iso_utc(max(ingests)) if ingests else None,
        "backlog_bytes": backlog_total,
    }


def _number(value: SqlValue) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def iso_utc(epoch: float) -> str:
    """Return one epoch as a UTC ISO-8601 second timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
