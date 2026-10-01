# Copyright (c) 2026 PitchAI. All rights reserved.
"""Join calls to historical account/window fingerprints, never current account use.

An anchor must contain positive measured usage. Idle zero-percent windows can
advertise a moving reset deadline and are unsuitable identity anchors. Exact
reset matches are tried first, then a one-second provider-rounding tolerance.
The call must fall within the advertised window, with two minutes of boundary
tolerance. Contradictory identities remain unjoined. This is an epoch join;
lease corroboration and any stronger timing/coverage controls are separate.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

type Json = str | int | float | bool | Sequence[Json] | Mapping[str, Json] | None
type Record = dict[str, Json]
type Index = dict[tuple[int, int], set[str]]
type Windows = dict[int, Record]
type CandidateRow = tuple[str, int, int, int]

WEEK_MINUTES = 10080
FIVE_HOUR_MINUTES = 300
PROGRESS_INTERVAL = 250000


def anchors(connection: sqlite3.Connection) -> Index:
    """Index positive account observations by duration and actual reset epoch.

    Returns:
        All account candidates for each observed duration/deadline pair.
    """
    result: Index = collections.defaultdict(set)
    rows = cast("Iterator[tuple[str, int, int]]", connection.execute(
        "SELECT DISTINCT account,duration,reset FROM observations WHERE used>0",
    ))
    for account, duration, reset in rows:
        result[duration, reset].add(account)
    return result


def select_windows(limits: Record) -> Windows:
    """Select weekly and five-hour fields according to their reported durations.

    Returns:
        Recorded windows indexed by their duration in minutes.

    Raises:
        ValueError: Two reported windows claim the same supported duration.
    """
    result: Windows = {}
    for name in ("primary", "secondary"):
        window = cast("Record | None", limits.get(name))
        if not window:
            continue
        minutes = cast("int | None", window.get("window_minutes"))
        if minutes in {FIVE_HOUR_MINUTES, WEEK_MINUTES}:
            if minutes in result:
                message = "Two reported windows have the same duration"
                raise ValueError(message)
            result[minutes] = window
    return result


def identify(timestamp: float, windows: Windows, index: Index) -> tuple[str | None, str]:
    """Require every matched window to support the same unambiguous account.

    Returns:
        A unique account or None, together with the join evidence grade.
    """
    matched: list[set[str]] = []
    mode = "exact_epoch"
    for minutes, window in windows.items():
        reset = window.get("resets_at")
        if not isinstance(reset, int):
            continue
        seconds = minutes * 60
        if not reset - seconds - 120 <= timestamp <= reset + 120:
            continue
        candidates = index.get((seconds, reset), set())
        if not candidates:
            candidates = index.get((seconds, reset - 1), set()) | index.get((seconds, reset + 1), set())
            if candidates:
                mode = "epoch_with_one_second_tolerance"
        if candidates:
            matched.append(candidates)
    if not matched:
        return None, "no_historical_epoch_anchor"
    consensus = set[str].intersection(*matched)
    if len(consensus) != 1:
        return None, "ambiguous_or_conflicting_epoch"
    return next(iter(consensus)), mode


def flatten(record: Record, metadata: tuple[int, int, int], index: Index) -> tuple[Json, ...]:
    """Keep disjoint token components and original windows for later analysis.

    Returns:
        The complete row in the declared joined-call schema order.
    """
    observed = cast("str", record["timestamp"])
    timestamp = datetime.datetime.fromisoformat(observed).timestamp()
    limits = cast("Record", record["rate_limits"] or {})
    windows = select_windows(limits)
    account, confidence = identify(timestamp, windows, index)
    if limits.get("limit_id") not in {None, "codex"}:
        account, confidence = None, "different_limit_id"
    weekly = windows.get(WEEK_MINUTES, {})
    five = windows.get(FIVE_HOUR_MINUTES, {})
    last = cast("dict[str, int]", record["last"])
    return (
        record["usage_key"], timestamp, observed[:10], record["cell"], record["source"],
        record["session"], record["turn"], record["model"], record["effort"], record["service_tier"],
        last["input_tokens"] - last["cached_input_tokens"], last["cached_input_tokens"],
        last["output_tokens"], last["reasoning_output_tokens"], record["counter_status"],
        int(cast("bool", record["reported_total_mismatch"])), *metadata,
        limits.get("plan_type"), account, confidence,
        weekly.get("used_percent"), weekly.get("resets_at"),
        five.get("used_percent"), five.get("resets_at"),
    )


def join(ledger: sqlite3.Connection, destination: sqlite3.Connection, index: Index) -> None:
    """Materialize the account join without changing the source ledger."""
    destination.execute("""
        CREATE TABLE calls (
            call_key TEXT PRIMARY KEY, timestamp REAL NOT NULL, day TEXT NOT NULL,
            cell TEXT, source TEXT, session TEXT, turn TEXT, model TEXT, effort TEXT, service_tier TEXT,
            uncached INTEGER NOT NULL, cached INTEGER NOT NULL, output INTEGER NOT NULL,
            reasoning INTEGER NOT NULL, counter_status TEXT NOT NULL, total_mismatch INTEGER NOT NULL,
            copies INTEGER NOT NULL, model_conflict INTEGER NOT NULL, effort_conflict INTEGER NOT NULL,
            plan TEXT, account TEXT, join_status TEXT NOT NULL,
            weekly_used REAL, weekly_reset INTEGER, five_used REAL, five_reset INTEGER)
    """)
    counts: collections.Counter[str] = collections.Counter()
    query = "SELECT data,copies,model_conflict,effort_conflict FROM calls"
    rows = cast("Iterator[CandidateRow]", ledger.execute(query))
    for number, row in enumerate(rows, start=1):
        record = cast("Record", json.loads(row[0]))
        result = flatten(record, (row[1], row[2], row[3]), index)
        counts[cast("str", result[21])] += 1
        destination.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", result)
        if number % PROGRESS_INTERVAL == 0:
            sys.stdout.write(json.dumps({"calls": number, "joins": counts}) + "\n")
            sys.stdout.flush()
    destination.execute("CREATE INDEX account_time ON calls(account,timestamp)")
    destination.execute("CREATE INDEX call_turn ON calls(turn)")
    destination.execute("CREATE INDEX call_day ON calls(day)")
    destination.commit()
    sys.stdout.write(json.dumps({"complete": True, "calls": sum(counts.values()), "joins": counts}) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Require completed ledger inputs and create a new joined database.

    Raises:
        ValueError: The ledger does not contain every expected extraction.
        FileExistsError: The requested destination already exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--quota", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-inputs", type=int, required=True)
    args = parser.parse_args()
    ledger_path = cast("Path", args.ledger)
    quota_path = cast("Path", args.quota)
    expected_inputs = cast("int", args.expected_inputs)
    with closing(sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)) as ledger:
        ledger.execute("BEGIN")
        if ledger.execute("SELECT COUNT(*) FROM inputs").fetchone()[0] != expected_inputs:
            message = "Wait for all expected extractions to finish ingesting"
            raise ValueError(message)
        with closing(sqlite3.connect(f"file:{quota_path}?mode=ro", uri=True)) as quota:
            index = anchors(quota)
        output = cast("Path", args.output)
        if output.exists():
            message = "Choose a new output; source evidence is never overwritten"
            raise FileExistsError(message)
        with closing(sqlite3.connect(output)) as destination:
            join(ledger, destination, index)


if __name__ == "__main__":
    main()
