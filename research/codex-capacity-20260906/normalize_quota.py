"""Normalize existing account observations without treating carried values as fresh.

The output keeps collection and provider times separate. Weekly dashboard fields
with a missing duration retain their explicit weekly meaning, with an inference
flag. Missing windows produce no observation, never a zero. Duplicate provider
observations collapse only when account, time, window, reset and percentage agree.
"""

import argparse
import collections
import datetime
import gzip
import hashlib
import json
import pathlib
import sqlite3


def instant(value):
    """Normalize ISO and epoch seconds to a UTC instant."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    return None


def windows(record):
    """Select window fields by their documented units, not their array position."""
    if record["kind"] == "quota_sample":
        for prefix, duration in (("weekly", 604800), ("five", 18000)):
            yield {
                "used_percent": record[f"{prefix}_used_percent"],
                "reset_at": record[f"{prefix}_reset_at"],
                "limit_window_seconds": record[f"{prefix}_window_seconds"] or duration,
            }, record[f"{prefix}_window_seconds"] is None
    else:
        for name in ("primary", "secondary"):
            window = record[name]
            if window:
                yield window, False


def observations(record):
    """Preserve provenance and freshness while making window tuples comparable."""
    kind = record["kind"]
    captured = record.get("captured_at") or record.get("sampled_at") or record.get("log_time")
    # Guardian usage is a direct provider read after a broker analytics probe.
    # Its extracted provider_observed_at is the earlier broker probe clock,
    # not the timestamp of the usage response. Use the snapshot capture proxy.
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
        if not 0 <= used <= 100 or duration not in (18000, 604800):
            raise ValueError("Unexpected quota percentage or duration")
        identity = [record["account"], observed, duration, reset, used]
        key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        freshness = record.get("values_source", "provider_observation")
        if kind == "guardian_snapshot":
            freshness = "guardian_direct_capture"
        yield (
            key, record["account"], observed, instant(captured), duration, int(reset), float(used),
            kind, freshness, int(bool(record.get("provider_stale", False))),
            int(provider_time is None), int(inferred_duration),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, action="append", required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Choose a new output; this evidence builder does not overwrite")
    connection = sqlite3.connect(args.output)
    connection.executescript("""
        CREATE TABLE observations (
            observation_key TEXT PRIMARY KEY, account TEXT NOT NULL, observed REAL NOT NULL,
            captured REAL, duration INTEGER NOT NULL, reset INTEGER NOT NULL, used REAL NOT NULL,
            source_kind TEXT NOT NULL, freshness TEXT NOT NULL, stale INTEGER NOT NULL,
            capture_time_only INTEGER NOT NULL, inferred_duration INTEGER NOT NULL,
            copies INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE manifests (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, counts TEXT NOT NULL);
    """)
    for path in args.input:
        counts = collections.Counter()
        with gzip.open(path, "rt") as stream:
            for line in stream:
                record = json.loads(line)
                counts[record["kind"]] += 1
                if record["kind"] not in ("quota_sample", "guardian_snapshot", "recovery_quota"):
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
        print(json.dumps({"input": path.name, "sha256": digest, "counts": counts}), flush=True)
    connection.execute("CREATE INDEX account_time ON observations(account,observed)")
    connection.execute("CREATE INDEX window_reset ON observations(duration,reset)")
    connection.commit()
    for row in connection.execute("SELECT account,COUNT(*),MIN(observed),MAX(observed) FROM observations GROUP BY account"):
        print(json.dumps(row))
    connection.close()


if __name__ == "__main__":
    main()
