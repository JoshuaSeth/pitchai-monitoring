"""Build a candidate call ledger without summing cumulative token counters.

Each source is read in recorded order. Unchanged cumulative counters carry no new
usage. Otherwise retain the reported last call, and record how it reconciles to
the cumulative delta. Missing earlier calls stay unallocated. Identical observed
events copied between sources collapse globally; distinct timestamps remain.
Conflicting model/effort evidence remains explicit for later cohort exclusion.
"""

import argparse
import collections
import gzip
import hashlib
import json
import pathlib
import sqlite3

COMPONENTS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def token_tuple(value):
    if not isinstance(value, dict):
        return None
    result = tuple(value.get(key) for key in COMPONENTS)
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in result):
        return None
    if result[1] > result[0] or result[3] > result[2]:
        return None
    return result


def candidate(event, previous):
    """Return a call only when telemetry records a new cumulative observation."""
    total = token_tuple(event["total"])
    last = token_tuple(event["last"])
    if total is not None and total == previous:
        return None, "unchanged_cumulative", total
    if last is None or last[0] + last[2] == 0:
        return None, "missing_or_invalid_last_call", total
    delta = tuple(current - before for current, before in zip(total, previous)) if total and previous else None
    if delta == last or previous is None and total == last:
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
    result["reported_total_mismatch"] = event["last"].get("total_tokens") != last[0] + last[2]
    return result, status, total


def initialize(connection):
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


def ingest(connection, path):
    fingerprint = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
    if connection.execute("SELECT 1 FROM inputs WHERE sha256=?", (fingerprint,)).fetchone():
        raise ValueError("This exact extraction is already ingested")
    counts = collections.Counter()
    previous_by_session = {}
    source = None
    manifest = complete = None
    connection.execute("BEGIN")
    with gzip.open(path, "rt") as stream:
        for line in stream:
            event = json.loads(line)
            kind = event["kind"]
            counts[kind] += 1
            if kind == "rollout_manifest":
                manifest = event
                continue
            if kind == "rollout_complete":
                complete = event
                continue
            if kind in ("rollout_source", "rollout_alias"):
                connection.execute("INSERT INTO sources VALUES (?,?,?)", (
                    event["cell"], event["source"], encoded(event),
                ))
                continue
            if kind != "token_event":
                raise ValueError("Unknown extraction record type")
            if event["source"] != source:
                source = event["source"]
                previous_by_session = {}
            limits = event["rate_limits"]
            if limits is not None:
                key = hashlib.sha256(encoded([event["usage_key"], limits]).encode()).hexdigest()
                connection.execute("INSERT INTO quotas VALUES (?,?,1,?) ON CONFLICT(quota_key) "
                                   "DO UPDATE SET copies=copies+1", (key, event["timestamp"], encoded(event)))
            observation, status, total = candidate(event, previous_by_session.get(event["session"]))
            if total is not None:
                previous_by_session[event["session"]] = total
            counts[status] += 1
            if observation is None:
                continue
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
            if counts["token_event"] % 200000 == 0:
                print(encoded({"progress_events": counts["token_event"], "cell": event["cell"]}), flush=True)
    if not manifest or not complete:
        raise ValueError("Extraction has no verified completion marker")
    if manifest["discovered_paths"] != counts["rollout_source"] + counts["rollout_alias"]:
        raise ValueError("Extraction does not account for every discovered source")
    summary = {"manifest": manifest, "counts": dict(counts), "sha256": fingerprint}
    connection.execute("INSERT INTO inputs VALUES (?,?)", (fingerprint, encoded(summary)))
    connection.commit()
    print(encoded(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=pathlib.Path, required=True)
    parser.add_argument("--input", type=pathlib.Path, action="append", required=True)
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA cache_size=-131072")
    initialize(connection)
    try:
        for path in args.input:
            ingest(connection, path)
        connection.execute("CREATE INDEX IF NOT EXISTS calls_timestamp ON calls(timestamp)")
        connection.execute("CREATE INDEX IF NOT EXISTS quotas_timestamp ON quotas(timestamp)")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
