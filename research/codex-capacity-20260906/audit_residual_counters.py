# Copyright (c) 2026 PitchAI. All rights reserved.
"""Measure residual complete-counter coincidences without declaring them replays.

The primary replay correction requires a shared turn identity. This audit asks
whether strict account-attributed survivors share all eight cumulative/recent
counters across sources with changed or absent turn identities. Coincidence alone is insufficient evidence
to remove consumption, so the output is a sensitivity analysis only.
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


class Counters(TypedDict):
    """Reported counter components, including the two subset counters."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


class Event(TypedDict):
    """Only the counter objects are inspected in the underlying event."""

    total: Counters | None
    last: Counters


type Candidate = tuple[str, float, str, str, str, str, str, float | None, str]
_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
_PROGRESS_EVERY = 250_000
_IMPORT = """
SELECT c.call_key,c.timestamp,c.day,c.account,c.cell||':'||c.source,c.session,c.turn,
       c.standard_usd,u.data
FROM cohort.account_calls c JOIN usage.calls u USING(call_key)
WHERE c.strict_eligible=1
"""
_ANALYSIS = """
CREATE INDEX counter_identity ON candidates(identity,timestamp);
CREATE TABLE coincidences AS
SELECT identity,COUNT(*) AS calls,COUNT(DISTINCT source) AS sources,
       COUNT(DISTINCT turn) AS turns,COUNT(DISTINCT session) AS sessions,
       SUM(turn IS NULL) AS missing_turn,
       COUNT(DISTINCT account) AS accounts,MIN(timestamp) AS first_at,
       MAX(timestamp) AS last_at,SUM(standard_usd) AS standard_usd
FROM candidates GROUP BY identity HAVING COUNT(*)>1;
CREATE TABLE ambiguous AS
SELECT c.*,g.first_at FROM candidates c JOIN coincidences g USING(identity)
WHERE g.sources>1 AND (g.turns>1 OR g.missing_turn>0);
"""


def import_candidates(connection: sqlite3.Connection) -> tuple[int, int]:
    """Inspect every strict survivor and preserve incomplete-counter records.

    Returns:
        Inspected candidates and candidates without cumulative counters.
    """
    inspected = 0
    incomplete = 0
    rows = cast("Iterator[Candidate]", iter(connection.execute(_IMPORT)))
    for row in rows:
        event = cast("Event", json.loads(row[-1]))
        total = event["total"]
        identity = row[0]
        if total is None:
            incomplete += 1
        else:
            complete = [total[field] for field in _FIELDS]
            complete.extend(event["last"][field] for field in _FIELDS)
            identity = hashlib.sha256(json.dumps(complete, separators=(",", ":")).encode()).hexdigest()
        connection.execute("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
                           (identity, *row[:-1]))
        inspected += 1
        if inspected % _PROGRESS_EVERY == 0:
            sys.stdout.write(json.dumps({"strict_candidates_inspected": inspected}) + "\n")
            sys.stdout.flush()
    return inspected, incomplete


def main() -> None:
    """Write anonymous counts and potential value sensitivity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cohort, ledger = cast("Path", args.cohort), cast("Path", args.ledger)
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("ATTACH DATABASE ? AS cohort", (f"file:{cohort}?mode=ro",))
        connection.execute("ATTACH DATABASE ? AS usage", (f"file:{ledger}?mode=ro",))
        connection.execute("""
            CREATE TABLE candidates(identity TEXT,call_key TEXT,timestamp REAL,day TEXT,
                account TEXT,source TEXT,session TEXT,turn TEXT,standard_usd REAL)
        """)
        inspected, incomplete = import_candidates(connection)
        connection.executescript(_ANALYSIS)
        connection.row_factory = sqlite3.Row
        group_rows = cast("list[sqlite3.Row]", connection.execute("""
            SELECT sources>1 AS cross_source,turns>1 AS changed_turn,COUNT(*) AS groups,
                   SUM(missing_turn>0) AS groups_with_missing_turn,
                   SUM(calls) AS calls,SUM(standard_usd) AS standard_usd,
                   MAX(last_at-first_at) AS maximum_time_separation_seconds
            FROM coincidences GROUP BY cross_source,changed_turn ORDER BY 1,2
        """).fetchall())
        daily_rows = cast("list[sqlite3.Row]", connection.execute("""
            SELECT account,day,COUNT(*) AS coincident_calls,SUM(standard_usd) AS standard_usd,
                   SUM(timestamp>first_at) AS later_calls,
                   SUM(CASE WHEN timestamp>first_at THEN standard_usd ELSE 0 END) AS later_standard_usd
            FROM ambiguous GROUP BY account,day ORDER BY account,day
        """).fetchall())
        result = {
            "schema": 1, "strict_candidates_inspected": inspected,
            "missing_cumulative_counters_preserved": incomplete,
            "coincidence_groups": [dict(row) for row in group_rows],
            "cross_source_changed_or_missing_turn_daily": [dict(row) for row in daily_rows],
            "qualification": "Complete-counter coincidence is not proof of replay. Primary keep decisions "
                             "are unchanged. Later-call value is an exclusion sensitivity, not a deduction "
                             "from verified consumption or a confidence interval.",
        }
    with cast("Path", args.output).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
