# Copyright (c) 2026 PitchAI. All rights reserved.
"""Normalize account observations while preserving source time and freshness.

Missing windows remain absent. Duplicate provider observations collapse only
when account, time, duration, reset and percentage agree. Guardian usage is a
direct provider response captured after its separate broker analytics probe.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import gzip
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
type Record = dict[str, Json]
type Observation = tuple[str, str, float, float | None, int, int, float, str, str, int, int, int]
MAX_PERCENT = 100


class QuotaWindow(TypedDict):
    """Provider window fields with explicit units."""

    used_percent: float | None
    reset_at: str | float | None
    limit_window_seconds: int | None


def instant(value: Json) -> float | None:
    """Convert a timestamp to epoch seconds.

    Returns:
        Parsed seconds, or None for absent and unsupported values.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value).timestamp()
    return None


def windows(record: Record) -> Iterator[tuple[QuotaWindow, bool]]:
    """Select fields by documented duration.

    Yields:
        Each available window and whether its duration was inferred.
    """
    if record["kind"] == "quota_sample":
        for prefix, duration in (("weekly", 604800), ("five", 18000)):
            yield {
                "used_percent": cast("float | None", record[f"{prefix}_used_percent"]),
                "reset_at": cast("str | float | None", record[f"{prefix}_reset_at"]),
                "limit_window_seconds": cast("int", record[f"{prefix}_window_seconds"] or duration),
            }, record[f"{prefix}_window_seconds"] is None
    else:
        for name in ("primary", "secondary"):
            window = record[name]
            if window:
                fields = cast("Record", window)
                yield {
                    "used_percent": cast("float | None", fields["used_percent"]),
                    "reset_at": cast("str | float | None", fields["reset_at"]),
                    "limit_window_seconds": cast("int | None", fields["limit_window_seconds"]),
                }, False


def observations(record: Record) -> Iterator[Observation]:
    """Preserve provenance and freshness in comparable quota tuples.

    Yields:
        Valid observations ready for the SQLite ledger.

    Raises:
        ValueError: A reported percentage or duration is outside its contract.
    """
    kind = cast("str", record["kind"])
    captured = record.get("captured_at") or record.get("sampled_at") or record.get("log_time")
    provider_time = None if kind == "guardian_snapshot" else record["provider_observed_at"]
    observed = instant(provider_time or captured)
    if observed is None:
        return
    for window, inferred_duration in windows(record):
        used = window["used_percent"]
        reset = instant(window["reset_at"])
        duration = window["limit_window_seconds"]
        if used is None or reset is None or duration is None:
            continue
        if not 0 <= used <= MAX_PERCENT or duration not in {18000, 604800}:
            message = "Unexpected quota percentage or duration"
            raise ValueError(message)
        identity: list[Json] = [record["account"], observed, duration, reset, used]
        key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        freshness = cast("str", record.get("values_source", "provider_observation"))
        if kind == "guardian_snapshot":
            freshness = "guardian_direct_capture"
        yield (
            key, cast("str", record["account"]), observed, instant(captured), duration, int(reset), float(used),
            kind, freshness, int(bool(record.get("provider_stale", False))),
            int(provider_time is None), int(inferred_duration),
        )


def ingest(connection: sqlite3.Connection, path: Path) -> None:
    """Import an allowlisted export and retain its digest and record counts."""
    counts: collections.Counter[str] = collections.Counter()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            record = cast("Record", json.loads(line))
            kind = cast("str", record["kind"])
            counts[kind] += 1
            if kind not in {"quota_sample", "guardian_snapshot", "recovery_quota"}:
                continue
            for row in observations(record):
                connection.execute("""
                    INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(observation_key) DO UPDATE SET copies=copies+1,
                    stale=MIN(stale,excluded.stale),
                    capture_time_only=MIN(capture_time_only,excluded.capture_time_only)
                """, row)
                counts["window_observations"] += 1
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    connection.execute("INSERT INTO manifests VALUES (?,?,?)", (path.name, digest, json.dumps(counts)))
    sys.stdout.write(json.dumps({"input": path.name, "sha256": digest, "counts": counts}) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Build a new normalized ledger.

    Raises:
        FileExistsError: The requested output already exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output, inputs = cast("Path", args.output), cast("list[Path]", args.input)
    if output.exists():
        message = "Choose a new output; this evidence builder does not overwrite"
        raise FileExistsError(message)
    with closing(sqlite3.connect(output)) as connection:
        connection.executescript("""
            CREATE TABLE observations (
                observation_key TEXT PRIMARY KEY, account TEXT NOT NULL, observed REAL NOT NULL,
                captured REAL, duration INTEGER NOT NULL, reset INTEGER NOT NULL, used REAL NOT NULL,
                source_kind TEXT NOT NULL, freshness TEXT NOT NULL, stale INTEGER NOT NULL,
                capture_time_only INTEGER NOT NULL, inferred_duration INTEGER NOT NULL,
                copies INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE manifests (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, counts TEXT NOT NULL);
        """)
        for path in inputs:
            ingest(connection, path)
        connection.execute("CREATE INDEX account_time ON observations(account,observed)")
        connection.execute("CREATE INDEX window_reset ON observations(duration,reset)")
        connection.commit()
        query = "SELECT account,COUNT(*),MIN(observed),MAX(observed) FROM observations GROUP BY account"
        summaries = cast("Iterator[tuple[str, int, float, float]]", connection.execute(query))
        for row in summaries:
            sys.stdout.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
