"""Join calls to historical account/window fingerprints, never current account use.

An anchor must contain positive measured usage. Idle zero-percent windows can
advertise a moving reset deadline and are unsuitable identity anchors. Exact
reset matches are tried first, then a one-second provider-rounding tolerance.
The call must fall within the advertised window, with two minutes of boundary
tolerance. Contradictory identities remain unjoined. This is an epoch join;
lease corroboration and any stronger timing/coverage controls are separate.
"""

import argparse
import collections
import datetime
import json
import pathlib
import sqlite3


def anchors(connection):
    """Index positive account observations by duration and actual reset epoch."""
    result = collections.defaultdict(set)
    for account, duration, reset in connection.execute(
        "SELECT DISTINCT account,duration,reset FROM observations WHERE used>0",
    ):
        result[duration, reset].add(account)
    return result


def select_windows(limits):
    """Return weekly and five-hour fields according to their reported durations."""
    result = {}
    for name in ("primary", "secondary"):
        window = limits.get(name)
        if not window:
            continue
        minutes = window.get("window_minutes")
        if minutes in (300, 10080):
            if minutes in result:
                raise ValueError("Two reported windows have the same duration")
            result[minutes] = window
    return result


def identify(timestamp, windows, index):
    """Require every matched window to support the same unambiguous account."""
    matched = []
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
    consensus = set.intersection(*matched)
    if len(consensus) != 1:
        return None, "ambiguous_or_conflicting_epoch"
    return next(iter(consensus)), mode


def flatten(record, metadata, index):
    """Keep disjoint token components and original window values for later analysis."""
    timestamp = datetime.datetime.fromisoformat(record["timestamp"]).timestamp()
    limits = record["rate_limits"] or {}
    windows = select_windows(limits)
    account, confidence = identify(timestamp, windows, index)
    if limits.get("limit_id") not in (None, "codex"):
        account, confidence = None, "different_limit_id"
    weekly = windows.get(10080, {})
    five = windows.get(300, {})
    last = record["last"]
    return (
        record["usage_key"], timestamp, record["timestamp"][:10], record["cell"], record["source"],
        record["session"], record["turn"], record["model"], record["effort"], record["service_tier"],
        last["input_tokens"] - last["cached_input_tokens"], last["cached_input_tokens"],
        last["output_tokens"], last["reasoning_output_tokens"], record["counter_status"],
        int(record["reported_total_mismatch"]), *metadata,
        limits.get("plan_type"), account, confidence,
        weekly.get("used_percent"), weekly.get("resets_at"),
        five.get("used_percent"), five.get("resets_at"),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=pathlib.Path, required=True)
    parser.add_argument("--quota", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--expected-inputs", type=int, required=True)
    args = parser.parse_args()
    ledger = sqlite3.connect(f"file:{args.ledger}?mode=ro", uri=True)
    ledger.execute("BEGIN")
    if ledger.execute("SELECT COUNT(*) FROM inputs").fetchone()[0] != args.expected_inputs:
        raise ValueError("Wait for all expected extractions to finish ingesting")
    quota = sqlite3.connect(f"file:{args.quota}?mode=ro", uri=True)
    index = anchors(quota)
    quota.close()
    if args.output.exists():
        raise FileExistsError("Choose a new output; source evidence is never overwritten")
    destination = sqlite3.connect(args.output)
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
    counts = collections.Counter()
    query = "SELECT data,copies,model_conflict,effort_conflict FROM calls"
    for number, row in enumerate(ledger.execute(query), start=1):
        record = json.loads(row[0])
        result = flatten(record, row[1:], index)
        counts[result[21]] += 1
        destination.execute("INSERT INTO calls VALUES (" + ",".join("?" for _ in result) + ")", result)
        if number % 250000 == 0:
            print(json.dumps({"calls": number, "joins": counts}), flush=True)
    destination.execute("CREATE INDEX account_time ON calls(account,timestamp)")
    destination.execute("CREATE INDEX call_turn ON calls(turn)")
    destination.execute("CREATE INDEX call_day ON calls(day)")
    destination.commit()
    print(json.dumps({"complete": True, "calls": sum(counts.values()), "joins": counts}), flush=True)
    destination.close()
    ledger.close()


if __name__ == "__main__":
    main()
