# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build account totals and fixed-hour quota cohorts from immutable evidence.

The SQL retains exclusions and uncertainty fields. Fixed UTC hours are selected
without looking at model, effort or apparent efficiency. Hourly slopes condition
on recovered workload and do not establish absolute hidden quota capacity.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TypedDict, cast


class Header(TypedDict):
    """Allowlisted session header fields."""

    session: str | None
    session_created_at: str | None
    event_at: str | None


class Source(TypedDict):
    """Typed projection of the source-header export."""

    kind: str
    cell: str
    source: str
    category: str
    status: str
    headers: list[Header]


def load_headers(connection: sqlite3.Connection, paths: list[Path]) -> None:
    """Import anonymous headers and retain the exact input content hashes.

    Raises:
        ValueError: If a header input has no final completion record.
    """
    connection.executescript("""
        CREATE TABLE headers(cell TEXT,source TEXT,category TEXT,outer_session TEXT,
            outer_at TEXT,header_count INTEGER,status TEXT,PRIMARY KEY(cell,source));
        CREATE TABLE header_inputs(path TEXT,sha256 TEXT,manifest TEXT,completion TEXT);
    """)
    for path in paths:
        cell = manifest = completion = ""
        with gzip.open(path, "rt") as stream:
            for line in stream:
                record = cast("Source", json.loads(line))
                if record["kind"] == "header_manifest":
                    cell, manifest = record["cell"], line.strip()
                elif record["kind"] == "header_complete":
                    completion = line.strip()
                elif record["kind"] == "source_header":
                    first = record["headers"][0] if record["headers"] else None
                    connection.execute("INSERT INTO headers VALUES (?,?,?,?,?,?,?)", (
                        cell, record["source"], record["category"], first["session"] if first else None,
                        first["session_created_at"] if first else None,
                        len(record["headers"]), record["status"],
                    ))
        if not completion or not manifest:
            message = "Header input is incomplete"
            raise ValueError(message)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        connection.execute("INSERT INTO header_inputs VALUES (?,?,?,?)", (
            path.name, digest, manifest, completion,
        ))
    connection.commit()


def load_broker(connection: sqlite3.Connection, path: Path) -> None:
    """Retain the frozen, already allowlisted broker export for event attribution."""
    connection.execute("CREATE TABLE broker_records(kind TEXT,data TEXT)")
    with gzip.open(path, "rt") as stream:
        for line in stream:
            record = cast("dict[str, object]", json.loads(line))
            connection.execute("INSERT INTO broker_records VALUES (?,?)", (record["kind"], line.strip()))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    connection.execute("CREATE TABLE broker_input(path TEXT,sha256 TEXT)")
    connection.execute("INSERT INTO broker_input VALUES (?,?)", (path.name, digest))
    connection.execute("CREATE INDEX broker_record_kind ON broker_records(kind)")
    connection.commit()


def main() -> None:
    """Run the retained SQL against read-only input databases.

    Raises:
        FileExistsError: If the output database already exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("joined", "replay", "prices", "quota", "broker", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--headers", type=Path, action="append", required=True)
    args = parser.parse_args()
    output = cast("Path", args.output)
    joined, replay = cast("Path", args.joined), cast("Path", args.replay)
    prices, quota = cast("Path", args.prices), cast("Path", args.quota)
    if output.exists():
        message = "Choose a new output; existing evidence is never overwritten"
        raise FileExistsError(message)
    with closing(sqlite3.connect(output)) as connection:
        connection.execute("ATTACH DATABASE ? AS usage", (f"file:{joined}?mode=ro",))
        connection.execute("ATTACH DATABASE ? AS replay", (f"file:{replay}?mode=ro",))
        connection.execute("ATTACH DATABASE ? AS prices", (f"file:{prices}?mode=ro",))
        connection.execute("ATTACH DATABASE ? AS quota", (f"file:{quota}?mode=ro",))
        load_headers(connection, cast("list[Path]", args.headers))
        load_broker(connection, cast("Path", args.broker))
        for script in ("account_calls.sql", "hour_cohorts.sql", "bank_epochs.sql"):
            connection.executescript(Path(__file__).with_name(script).read_text(encoding="utf-8"))
            sys.stdout.write(json.dumps({"completed_sql": script}) + "\n")
            sys.stdout.flush()
        counts = cast("list[tuple[str, int]]", connection.execute("""
            SELECT 'account_calls',COUNT(*) FROM account_calls
            UNION ALL SELECT 'candidate_hours',COUNT(*) FROM hour_windows
            UNION ALL SELECT 'eligible_hours',COUNT(*) FROM hour_windows WHERE timing_eligible=1
            UNION ALL SELECT 'exposure_rows',COUNT(*) FROM exposures
            UNION ALL SELECT 'bank_credit_disappearances',COUNT(*) FROM bank_losses
            UNION ALL SELECT 'positive_weekly_segments',COUNT(*) FROM epochs
        """).fetchall())
        sys.stdout.write(json.dumps({"complete": True, "counts": dict(counts)}) + "\n")


if __name__ == "__main__":
    main()
