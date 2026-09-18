# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compare prior logical-turn totals with current call telemetry, without identities.

The earlier export selected one source candidate per turn. This comparison keeps
that source restriction separate from current replay correction. It reads only
numeric telemetry, hashes and classification fields; raw turn IDs are hashed in
memory and are never written. Neither export is assumed to be complete.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

type Comparison = tuple[str, str, int, int, int, int, int, int, int, int, int]


class Counters(TypedDict):
    """Counter totals, with cache and reasoning retained as subsets."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


class Summary(TypedDict):
    """Aggregate comparison within a prior integrity stratum."""

    outcome: str
    prior_integrity_anomaly: bool
    turns: int
    prior: Counters
    current: Counters


class Provenance(TypedDict):
    """Source and token confidence for nonzero discrepancies only."""

    scope: str
    outcome: str
    source_class: str
    token_confidence: str
    control_status: str
    turn_status: str
    turns: int
    prior_input_tokens: int
    current_input_tokens: int


_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
_SCOPES = ("canonical_source", "all_candidates", "replay_corrected")


def import_prior(connection: sqlite3.Connection, path: Path) -> dict[str, int]:
    """Import only modern turns with a complete nonnegative numeric tuple.

    Returns:
        Import status counts, including explicitly excluded legacy and unobserved turns.
    """
    connection.execute("""
        CREATE TABLE prior(turn TEXT PRIMARY KEY,source TEXT,integrity INTEGER,
                           input INTEGER,cached INTEGER,output INTEGER,reasoning INTEGER,
                           source_class TEXT,token_confidence TEXT,control_status TEXT,status TEXT)
    """)
    connection.execute("CREATE TABLE discrepancies(turn TEXT,scope TEXT,outcome TEXT,current_input INTEGER)")
    counts: Counter[str] = Counter()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            counts["rows"] += 1
            if not row["turn_id"]:
                counts["no_modern_turn_id"] += 1
                continue
            values = [row[field] for field in _FIELDS]
            if not all(value.isdecimal() for value in values):
                counts["missing_or_invalid_tokens"] += 1
                continue
            identity = hashlib.sha256(row["turn_id"].encode()).hexdigest()
            connection.execute("INSERT INTO prior VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                identity, row["canonical_source_sha256"], int(row["integrity_anomaly"]),
                *(int(value) for value in values),
                row["source_class"], row["token_confidence"], row["control_reconciliation_status"], row["status"],
            ))
            counts["imported"] += 1
    connection.commit()
    return dict(counts)


def compare(connection: sqlite3.Connection, scope: str, cutoff: float) -> Iterator[Comparison]:
    """Aggregate current calls at the prior snapshot boundary, then compare turns.

    Yields:
        Hashed turn, outcome, integrity flag, and prior/current four-counter tuples.
    """
    query = """
        SELECT p.turn,p.integrity,p.input,p.cached,p.output,p.reasoning,
               COUNT(c.call_key),COALESCE(SUM(c.uncached+c.cached),0),
               COALESCE(SUM(c.cached),0),COALESCE(SUM(c.output),0),
               COALESCE(SUM(c.reasoning),0)
        FROM prior p LEFT JOIN usage.calls c
          ON c.turn=p.turn AND c.timestamp<:cutoff AND (
              :scope='all_candidates' OR (:scope='canonical_source' AND c.source=p.source)
              OR (:scope='replay_corrected' AND EXISTS (
                  SELECT 1 FROM replay.decisions d WHERE d.call_key=c.call_key AND d.keep_primary=1)))
        GROUP BY p.turn
    """
    rows = cast("Iterator[tuple[str, int, int, int, int, int, int, int, int, int, int]]",
                iter(connection.execute(query, {"cutoff": cutoff, "scope": scope})))
    for row in rows:
        old, new = row[2:6], row[7:]
        if row[6] == 0:
            outcome = "no_current_calls_before_cutoff" if any(old) else "zero_prior_no_current_calls"
        elif old == new:
            outcome = "exact_four_counter_match"
        elif all(now <= before for before, now in zip(old, new, strict=True)):
            outcome = "current_componentwise_lower"
        elif all(now >= before for before, now in zip(old, new, strict=True)):
            outcome = "current_componentwise_higher"
        else:
            outcome = "mixed_component_differences"
        if outcome not in {"exact_four_counter_match", "zero_prior_no_current_calls"}:
            connection.execute("INSERT INTO discrepancies VALUES (?,?,?,?)", (row[0], scope, outcome, new[0]))
        yield row[0], outcome, row[1], *old, *new


def provenance(connection: sqlite3.Connection) -> list[Provenance]:
    """Classify mismatches using the earlier ledger's declared evidence confidence.

    Returns:
        Anonymous grouped counts and corresponding input totals.
    """
    rows = cast("Iterator[tuple[str, str, str, str, str, str, int, int, int]]", iter(connection.execute("""
        SELECT d.scope,d.outcome,p.source_class,p.token_confidence,p.control_status,p.status,
               COUNT(*),SUM(p.input),SUM(d.current_input)
        FROM discrepancies d JOIN prior p USING(turn) GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6
    """)))
    return [{"scope": row[0], "outcome": row[1], "source_class": row[2],
             "token_confidence": row[3], "control_status": row[4], "turn_status": row[5],
             "turns": row[6], "prior_input_tokens": row[7], "current_input_tokens": row[8]} for row in rows]


def summarize(rows: Iterator[Comparison]) -> list[Summary]:
    """Sum corresponding numeric fields within each outcome and integrity stratum.

    Returns:
        Anonymous turn counts and token totals; cached and reasoning remain subsets.
    """
    groups: dict[tuple[str, int], list[int]] = {}
    for row in rows:
        key = row[1], row[2]
        bucket = groups.setdefault(key, [0] * 9)
        bucket[0] += 1
        for index, value in enumerate(row[3:], start=1):
            bucket[index] += value
    return [{
        "outcome": outcome, "prior_integrity_anomaly": bool(integrity),
        "turns": values[0],
        "prior": {"input_tokens": values[1], "cached_input_tokens": values[2],
                  "output_tokens": values[3], "reasoning_output_tokens": values[4]},
        "current": {"input_tokens": values[5], "cached_input_tokens": values[6],
                    "output_tokens": values[7], "reasoning_output_tokens": values[8]},
    } for (outcome, integrity), values in sorted(groups.items())]


def main() -> None:
    """Read frozen inputs and write a bounded anonymous reconciliation receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prior", "joined", "replay", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()
    prior = cast("Path", args.prior)
    replay, output = cast("Path", args.replay), cast("Path", args.output)
    cutoff = dt.datetime.fromisoformat(cast("str", args.cutoff))
    with closing(sqlite3.connect(":memory:", uri=True)) as connection:
        connection.execute("ATTACH DATABASE ? AS usage", (f"file:{cast('Path', args.joined)}?mode=ro",))
        connection.execute("ATTACH DATABASE ? AS replay", (f"file:{replay}?mode=ro",))
        imported = import_prior(connection, prior)
        scopes: dict[str, list[Summary]] = {}
        for scope in _SCOPES:
            scopes[scope] = summarize(compare(connection, scope, cutoff.timestamp()))
            sys.stdout.write(json.dumps({"scope_complete": scope}) + "\n")
            sys.stdout.flush()
        differences = provenance(connection)
    with prior.open("rb") as stream:
        prior_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "schema": 1, "prior_sha256": prior_hash, "prior_cutoff_exclusive": cutoff.isoformat(),
        "import": imported, "scopes": scopes, "discrepancy_provenance": differences,
        "qualifications": [
            "Only prior modern turns with numeric counters are compared. Legacy and unobserved turns remain gaps.",
            ("The earlier ledger selected one source candidate per turn. Canonical-source and replay-corrected "
             "scopes answer different questions and must not be added together."),
            ("Current calls are cut by event time; earlier turns can include retrospective or incomplete "
             "records. Agreement is corroboration of counters, not proof of live execution or payment."),
            "Input includes cached input; output includes reasoning output. Do not sum all four fields.",
        ],
    }
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
