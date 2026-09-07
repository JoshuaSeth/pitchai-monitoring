# Copyright (c) 2026 PitchAI. All rights reserved.
"""Find retimestamped copies using a turn ID and complete token counters.

This creates a sidecar without changing the original candidate ledger. Matching
token counts alone never identify a replay. Missing session, turn or cumulative
counters leave a record unique. Same-source repetitions remain ambiguous; the
primary keep decision only collapses identities seen in different source files.
Forks can replace session IDs while retaining turn IDs and all eight counters.
The session is therefore required to be present but is not part of the identity.
Earliest time is a candidate original timestamp, not proof of live execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Iterator


class Tokens(TypedDict):
    """Disjoint-counter source fields; cached and reasoning are subsets."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


class Event(TypedDict):
    """Allowlisted identity fields in the candidate ledger."""

    session: str | None
    turn: str | None
    source: str
    total: Tokens | None
    last: Tokens


type Candidate = tuple[str, str, str | None, str | None, str]
type Identity = tuple[str, str, str, str, str | None, str | None, str]
_PROGRESS_EVERY = 250_000
_TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def identities(connection: sqlite3.Connection) -> Iterator[Identity]:
    """Hash complete counter identities while preserving uncertain records.

    Yields:
        Original call key, semantic key, timestamp, source, model, effort and mode.
    """
    query = "SELECT call_key,timestamp,model,effort,data FROM calls"
    rows = cast("Iterator[Candidate]", iter(connection.execute(query)))
    for key, timestamp, model, effort, data in rows:
        event = cast("Event", json.loads(data))
        total = event["total"]
        mode = "global_turn_full_counters"
        if event["session"] is None or event["turn"] is None or total is None:
            semantic_key = key
            mode = "insufficient_identity_preserved"
        else:
            counters = [total[field] for field in _TOKEN_FIELDS]
            recent = [event["last"][field] for field in _TOKEN_FIELDS]
            identity = [event["turn"], counters, recent]
            semantic_key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        yield key, semantic_key, timestamp, event["source"], model, effort, mode


def summarize(connection: sqlite3.Connection) -> None:
    """Persist groups and a conservative cross-source replay decision."""
    connection.executescript("""
        CREATE INDEX identity_group ON identities(semantic_key,timestamp);
        CREATE TABLE groups AS
        SELECT semantic_key,MIN(timestamp) AS first_at,MAX(timestamp) AS last_at,
               COUNT(*) AS members,COUNT(DISTINCT source) AS sources,
               COUNT(DISTINCT model) AS models,COUNT(DISTINCT effort) AS efforts
        FROM identities GROUP BY semantic_key;
        CREATE UNIQUE INDEX group_identity ON groups(semantic_key);
        CREATE TABLE decisions AS
        SELECT i.call_key,i.semantic_key,
               CASE WHEN g.sources>1 AND i.timestamp>g.first_at THEN 0 ELSE 1 END AS keep_primary,
               CASE WHEN g.members=1 THEN 'unique_identity'
                    WHEN g.sources=1 THEN 'same_source_repetition_preserved'
                    WHEN i.timestamp=g.first_at THEN 'earliest_cross_source_copy'
                    ELSE 'later_cross_source_replay' END AS decision,
               g.models>1 AS model_conflict,g.efforts>1 AS effort_conflict
        FROM identities i JOIN groups g USING(semantic_key);
        CREATE UNIQUE INDEX decision_call ON decisions(call_key);
    """)
    counts = cast("list[tuple[str, int]]", connection.execute(
        "SELECT decision,COUNT(*) FROM decisions GROUP BY decision",
    ).fetchall())
    sys.stdout.write(json.dumps({"complete": True, "decisions": dict(counts)}) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Audit immutable candidate records and fail if the sidecar already exists.

    Raises:
        FileExistsError: If the requested output exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ledger = cast("Path", args.ledger)
    output = cast("Path", args.output)
    if output.exists():
        message = "Choose a new output; original evidence and existing audits are never overwritten"
        raise FileExistsError(message)
    with (
        closing(sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(output)) as destination,
    ):
        destination.execute("""
            CREATE TABLE identities(call_key TEXT PRIMARY KEY,semantic_key TEXT NOT NULL,
                timestamp TEXT NOT NULL,source TEXT NOT NULL,model TEXT,effort TEXT,mode TEXT NOT NULL)
        """)
        for number, row in enumerate(identities(source), start=1):
            destination.execute("INSERT INTO identities VALUES (?,?,?,?,?,?,?)", row)
            if number % _PROGRESS_EVERY == 0:
                sys.stdout.write(json.dumps({"identified_calls": number}) + "\n")
                sys.stdout.flush()
        destination.commit()
        summarize(destination)


if __name__ == "__main__":
    main()
