# Copyright (c) 2026 PitchAI. All rights reserved.
"""Export anonymous retained scheduling outcomes without replaying any work.

These counters were derived from rollout cumulative boundaries by the CLI.
They are corroborating projections, not an independent provider request ledger.
Only token counters, times, status labels and hashed identities leave the source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
type TokenRow = tuple[str, str | None, int, int, int, int, int, str, str]

_COVERAGE = """
SELECT COUNT(*),MIN(observed_at),MAX(observed_at),COUNT(observed_total_tokens),
       COUNT(observed_capacity_points),
       SUM(INSTR(outcome_payload_json,'"service_tier"')>0)
FROM scheduling_decision_outcome WHERE observed_at < ?
"""
_ROWS = """
SELECT outcome_id,turn_id,observed_input_tokens,observed_cached_input_tokens,
       observed_output_tokens,observed_reasoning_output_tokens,observed_total_tokens,
       observed_at,outcome_payload_json
FROM scheduling_decision_outcome
WHERE observed_at < ? AND observed_total_tokens IS NOT NULL ORDER BY sequence
"""


def digest(value: str) -> str:
    """Hash an exact identity for comparison without disclosing it.

    Returns:
        Its SHA-256 hexadecimal digest.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def emit(kind: str, **fields: Json) -> None:
    """Write one deterministic, allowlisted observation."""
    sys.stdout.write(json.dumps({"kind": kind, **fields}, sort_keys=True) + "\n")


def export(connection: sqlite3.Connection, source: str, cutoff: str) -> None:
    """Record full outcome coverage and every retained numeric observation."""
    coverage = cast("tuple[int, str | None, str | None, int, int, int | None]",
                    connection.execute(_COVERAGE, (cutoff,)).fetchone())
    status_rows = cast("list[tuple[str, str, int]]", connection.execute("""
        SELECT cost_status,detail_code,COUNT(*) FROM scheduling_decision_outcome
        WHERE observed_at < ? GROUP BY cost_status,detail_code ORDER BY cost_status,detail_code
    """, (cutoff,)).fetchall())
    statuses: list[Json] = [{"cost_status": cost, "detail_code": detail, "rows": count}
                            for cost, detail, count in status_rows]
    emit("scheduling_manifest", source=source, cutoff=cutoff, rows=coverage[0],
         first_at=coverage[1], last_at=coverage[2], numeric_rows=coverage[3],
         capacity_point_rows=coverage[4], service_tier_key_rows=coverage[5], statuses=statuses)
    rows = cast("Iterator[TokenRow]", iter(connection.execute(_ROWS, (cutoff,))))
    count = 0
    for row in rows:
        emit_usage(source, row)
        count += 1
    emit("scheduling_complete", source=source, numeric_rows=count)


def emit_usage(source: str, row: TokenRow) -> None:
    """Project the SQL token tuple with only hashed identities and observed times."""
    data = cast("dict[str, Json]", json.loads(row[8]))
    timestamps = cast("dict[str, Json]", data["timestamps"])
    emit("scheduling_usage", source=source, outcome=digest(row[0]), turn=digest(row[1]) if row[1] else None,
         input=row[2], cached=row[3], output=row[4], reasoning=row[5], total=row[6],
         observed_at=row[7], started_at=timestamps.get("turn_started_at"),
         terminal_at=timestamps.get("terminal_at"))


def main() -> None:
    """Read one explicit source in a stable read transaction."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()
    path = cast("Path", args.database)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        export(connection, cast("str", args.source), cast("str", args.cutoff))


if __name__ == "__main__":
    main()
