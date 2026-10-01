# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build a candidate call ledger without summing cumulative token counters.

Each source is read in recorded order. Unchanged cumulative counters carry no new
usage. Otherwise retain the reported last call, and record how it reconciles to
the cumulative delta. Missing earlier calls stay unallocated. Identical observed
events copied between sources collapse globally; distinct timestamps remain.
Conflicting model/effort evidence remains explicit for later cohort exclusion.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

type Json = str | int | float | bool | Sequence[Json] | Mapping[str, Json] | None
type Event = dict[str, Json]
type Tokens = tuple[int, int, int, int]
type Previous = dict[str | None, Tokens]

COMPONENTS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
PROGRESS_INTERVAL = 200000


def encoded(value: Json) -> str:
    """Serialize deterministic JSON.

    Returns:
        A sorted compact representation suitable for hashes and stored evidence.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def token_tuple(value: Json) -> Tokens | None:
    """Validate the four component counters without coercion.

    Returns:
        Nonnegative counters with valid subsets, or None for invalid telemetry.
    """
    if not isinstance(value, dict):
        return None
    result: list[int] = []
    for key in COMPONENTS:
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            return None
        result.append(item)
    if result[1] > result[0] or result[3] > result[2]:
        return None
    return result[0], result[1], result[2], result[3]


def candidate(event: Event, previous: Tokens | None) -> tuple[Event | None, str, Tokens | None]:
    """Classify a new cumulative observation.

    Returns:
        A candidate or missingness, its status and the valid cumulative tuple.
    """
    total = token_tuple(event["total"])
    last = token_tuple(event["last"])
    if total is not None and total == previous:
        return None, "unchanged_cumulative", total
    if last is None or last[0] + last[2] == 0:
        return None, "missing_or_invalid_last_call", total
    delta = None
    if total and previous:
        delta = (total[0] - previous[0], total[1] - previous[1],
                 total[2] - previous[2], total[3] - previous[3])
    if delta == last or (previous is None and total == last):
        status, rank = "last_call_reconciles", 4
    elif previous is None:
        status, rank = "first_observation_with_prior_cumulative_usage", 2
    elif delta and any(item < 0 for item in delta):
        status, rank = "counter_reset_or_rollback", 1
    else:
        status, rank = "last_call_does_not_reconcile", 1
    result = dict(event)
    result["counter_status"] = status
    result["counter_delta"] = delta
    result["selection_rank"] = rank + int(bool(event["model"]))
    reported_last = cast("Mapping[str, Json]", event["last"])
    result["reported_total_mismatch"] = reported_last.get("total_tokens") != last[0] + last[2]
    return result, status, total


def initialize(connection: sqlite3.Connection) -> None:
    """Create the appendable candidate schema when it is first opened."""
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS inputs (sha256 TEXT PRIMARY KEY, manifest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources (cell TEXT, source TEXT, data TEXT NOT NULL,
            PRIMARY KEY(cell, source));
        CREATE TABLE IF NOT EXISTS calls (call_key TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
            model TEXT, effort TEXT, rank INTEGER NOT NULL, copies INTEGER NOT NULL,
            model_conflict INTEGER NOT NULL, effort_conflict INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quotas (quota_key TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
            copies INTEGER NOT NULL, data TEXT NOT NULL);
    """)


def record_usage(connection: sqlite3.Connection, event: Event, previous: Previous,
                 counts: collections.Counter[str]) -> None:
    """Retain quota evidence and insert or reconcile one candidate call."""
    limits = event["rate_limits"]
    if limits is not None:
        key = hashlib.sha256(encoded([event["usage_key"], limits]).encode()).hexdigest()
        connection.execute("INSERT INTO quotas VALUES (?,?,1,?) ON CONFLICT(quota_key) "
                           "DO UPDATE SET copies=copies+1", (key, event["timestamp"], encoded(event)))
    session = cast("str | None", event["session"])
    observation, status, total = candidate(event, previous.get(session))
    if total is not None:
        previous[session] = total
    counts[status] += 1
    if observation is None:
        return
    connection.execute("""
        INSERT INTO calls VALUES (?,?,?,?,?,1,0,0,?)
        ON CONFLICT(call_key) DO UPDATE SET
            copies=copies+1,
            model_conflict=model_conflict OR
                (model IS NOT NULL AND excluded.model IS NOT NULL AND model!=excluded.model),
            effort_conflict=effort_conflict OR
                (effort IS NOT NULL AND excluded.effort IS NOT NULL AND effort!=excluded.effort),
            model=CASE WHEN excluded.rank>rank THEN excluded.model ELSE model END,
            effort=CASE WHEN excluded.rank>rank THEN excluded.effort ELSE effort END,
            data=CASE WHEN excluded.rank>rank THEN excluded.data ELSE data END,
            rank=MAX(rank,excluded.rank)
    """, (event["usage_key"], event["timestamp"], event["model"], event["effort"],
          observation["selection_rank"], encoded(observation)))
    if counts["token_event"] % PROGRESS_INTERVAL == 0:
        sys.stdout.write(encoded({"progress_events": counts["token_event"], "cell": event["cell"]}) + "\n")
        sys.stdout.flush()


def ingest(connection: sqlite3.Connection, path: Path) -> None:
    """Import one completed extraction atomically.

    Raises:
        ValueError: The input is duplicated, incomplete or has unknown records.
    """
    with path.open("rb") as stream:
        fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
    if connection.execute("SELECT 1 FROM inputs WHERE sha256=?", (fingerprint,)).fetchone():
        message = "This exact extraction is already ingested"
        raise ValueError(message)
    counts: collections.Counter[str] = collections.Counter()
    previous_by_session: Previous = {}
    source: Json = None
    manifest: Event | None = None
    complete: Event | None = None
    connection.execute("BEGIN")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            event = cast("Event", json.loads(line))
            kind = cast("str", event["kind"])
            counts[kind] += 1
            if kind == "rollout_manifest":
                manifest = event
                continue
            if kind == "rollout_complete":
                complete = event
                continue
            if kind in {"rollout_source", "rollout_alias"}:
                connection.execute("INSERT INTO sources VALUES (?,?,?)", (
                    event["cell"], event["source"], encoded(event),
                ))
                continue
            if kind != "token_event":
                message = "Unknown extraction record type"
                raise ValueError(message)
            if event["source"] != source:
                source = event["source"]
                previous_by_session = {}
            record_usage(connection, event, previous_by_session, counts)
    if not manifest or not complete:
        message = "Extraction has no verified completion marker"
        raise ValueError(message)
    if manifest["discovered_paths"] != counts["rollout_source"] + counts["rollout_alias"]:
        message = "Extraction does not account for every discovered source"
        raise ValueError(message)
    summary = {"manifest": manifest, "counts": dict(counts), "sha256": fingerprint}
    connection.execute("INSERT INTO inputs VALUES (?,?)", (fingerprint, encoded(summary)))
    connection.commit()
    sys.stdout.write(encoded(summary) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Import requested extractions and create ledger indexes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--input", type=Path, action="append", required=True)
    args = parser.parse_args()
    with closing(sqlite3.connect(cast("Path", args.database))) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA cache_size=-131072")
        initialize(connection)
        for path in cast("list[Path]", args.input):
            ingest(connection, path)
        connection.execute("CREATE INDEX IF NOT EXISTS calls_timestamp ON calls(timestamp)")
        connection.execute("CREATE INDEX IF NOT EXISTS quotas_timestamp ON quotas(timestamp)")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


if __name__ == "__main__":
    main()
