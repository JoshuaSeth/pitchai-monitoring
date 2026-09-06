"""Stream allowlisted token and rate-limit observations from existing rollouts.

Inputs are existing search indexes and explicitly named session roots. File size
is frozen before each read; event timestamps additionally obey a UTC cutoff.
No prompts, answers, tool payloads, instructions, account IDs or paths are emitted.
Repeated events remain candidates for the separate global deduplication stage.
"""

import argparse
import collections
import datetime
import glob
import hashlib
import json
import os
import pathlib
import sqlite3
import sys

TOKEN_KEYS = (
    "input_tokens", "cached_input_tokens", "output_tokens",
    "reasoning_output_tokens", "total_tokens",
)
MARKERS = (b'"token_count"', b'"turn_context"', b'"session_meta"', b'"task_started"')


def emit(kind, **fields):
    print(json.dumps({"kind": kind, **fields}, sort_keys=True, separators=(",", ":")))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def tokens(value):
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in TOKEN_KEYS}


def limits(value):
    if not isinstance(value, dict):
        return None
    result = {key: value.get(key) for key in ("limit_id", "limit_name", "plan_type")}
    for name in ("primary", "secondary"):
        current = value.get(name)
        result[name] = {key: current.get(key) for key in (
            "used_percent", "window_minutes", "resets_at",
        )} if isinstance(current, dict) else None
    credit = value.get("credits")
    if isinstance(credit, dict):
        result["credits"] = {key: credit.get(key) for key in (
            "has_credits", "unlimited", "balance",
        )}
    return result


def scan(path, cell, cutoff):
    source = digest(str(path))
    stats = collections.Counter()
    content_hash = hashlib.sha256()
    model = effort = tier = turn = session = version = provider = None
    first = last = None
    try:
        before = path.stat()
        with path.open("rb") as stream:
            while stream.tell() < before.st_size:
                offset = stream.tell()
                line = stream.readline(before.st_size - offset)
                content_hash.update(line)
                stats["bytes"] += len(line)
                stats["lines"] += 1
                if not any(marker in line for marker in MARKERS):
                    continue
                stats["candidate_lines"] += 1
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    stats["candidate_json_errors"] += 1
                    continue
                if not isinstance(event, dict):
                    stats["non_object_candidates"] += 1
                    continue
                when = event.get("timestamp")
                if not isinstance(when, str):
                    stats["missing_timestamp"] += 1
                    continue
                try:
                    observed = datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
                except ValueError:
                    stats["invalid_timestamp"] += 1
                    continue
                if observed.tzinfo is None:
                    stats["naive_timestamp"] += 1
                    continue
                if observed >= cutoff:
                    stats["after_cutoff"] += 1
                    continue
                when = observed.astimezone(datetime.timezone.utc).isoformat()
                first = min(first, when) if first else when
                last = max(last, when) if last else when
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    continue
                event_type = event.get("type")
                if event_type == "session_meta":
                    stats["session_meta"] += 1
                    session = digest(str(payload.get("id")))
                    version = payload.get("cli_version")
                    provider = payload.get("model_provider")
                    model = effort = tier = turn = None
                elif event_type == "turn_context":
                    stats["turn_context"] += 1
                    model = payload.get("model")
                    effort = payload.get("effort") or payload.get("reasoning_effort")
                    tier = payload.get("service_tier")
                    turn = payload.get("turn_id") or turn
                elif event_type == "event_msg" and payload.get("type") == "task_started":
                    turn = payload.get("turn_id") or turn
                elif event_type == "event_msg" and payload.get("type") == "token_count":
                    stats["token_events"] += 1
                    info = payload.get("info") or {}
                    total = tokens(info.get("total_token_usage"))
                    recent = tokens(info.get("last_token_usage"))
                    usage_key = digest(json.dumps([when, total, recent], sort_keys=True))
                    emit("token_event", cell=cell, source=source, offset=offset,
                         timestamp=when, session=session, turn=digest(turn) if turn else None,
                         cli_version=version, provider=provider, model=model, effort=effort,
                         service_tier=tier, total=total, last=recent,
                         rate_limits=limits(payload.get("rate_limits")), usage_key=usage_key)
        after = path.stat()
        status = "read"
        if after.st_size < before.st_size:
            status = "source_shrank_during_read"
        elif after.st_mtime_ns != before.st_mtime_ns and after.st_size == before.st_size:
            status = "source_rewritten_during_read"
        emit("rollout_source", cell=cell, source=source, status=status,
             initial_bytes=before.st_size, final_bytes=after.st_size, first_at=first,
             last_at=last, prefix_sha256=content_hash.hexdigest(), **stats)
    except (OSError, ValueError) as error:
        emit("rollout_source", cell=cell, source=source, status=type(error).__name__, **stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--index", action="append", default=[])
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--private-source-map")
    args = parser.parse_args()
    cutoff = datetime.datetime.fromisoformat(args.cutoff.replace("Z", "+00:00"))
    paths = set()
    for name in args.index:
        connection = sqlite3.connect(f"file:{name}?mode=ro", uri=True)
        paths.update(pathlib.Path(row[0]) for row in connection.execute("SELECT path FROM rollout_files"))
        connection.close()
    for pattern in args.root:
        for root in glob.glob(pattern):
            paths.update(pathlib.Path(root).rglob("*.jsonl"))
    if args.private_source_map:
        destination = pathlib.Path(args.private_source_map)
        with open(destination, "w", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            json.dump({digest(str(path)): str(path) for path in paths}, stream, sort_keys=True)
    emit("rollout_manifest", cell=args.cell, cutoff=args.cutoff, discovered_paths=len(paths),
         schema=1, extracted_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    inodes = {}
    for number, path in enumerate(sorted(paths), start=1):
        try:
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity in inodes:
                emit("rollout_alias", cell=args.cell, source=digest(str(path)),
                     canonical_source=inodes[identity], reason="same_device_and_inode")
                continue
            inodes[identity] = digest(str(path))
        except OSError:
            pass
        scan(path, args.cell, cutoff)
        if number % 500 == 0:
            print(f"{args.cell}: scanned {number}/{len(paths)} paths", file=sys.stderr)
    emit("rollout_complete", cell=args.cell, discovered_paths=len(paths))


if __name__ == "__main__":
    main()
