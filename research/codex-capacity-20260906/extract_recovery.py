"""Extract anonymous historical quota/lease evidence from broker recovery logs.

Run on the broker host. Decode only actual HTTP-409 JSON response objects. Never
retain log message text, credentials, account references, labels or client names.
"""

import argparse
import collections
import gzip
import hashlib
import json
import pathlib
import re
import sqlite3


def hashed(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def emit(kind, **fields):
    print(json.dumps({"kind": kind, **fields}, sort_keys=True, separators=(",", ":")))


def window(value):
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in (
        "used_percent", "limit_window_seconds", "reset_at", "reset_after_seconds",
    )}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--alias-map", type=pathlib.Path)
    parser.add_argument("--cell", default="dev-main-and-monitoring")
    args = parser.parse_args()
    if args.alias_map:
        identities = json.loads(args.alias_map.read_text())
        labels = identities["labels"]
        account_ids = identities["account_ids"]
    else:
        connection = sqlite3.connect(
            "file:/srv/codex-usage-dashboard/usage-history.sqlite3?mode=ro", uri=True,
        )
        rows = connection.execute(
            "SELECT DISTINCT account_ref, account_label FROM account_usage_samples "
            "WHERE sampled_at < ? ORDER BY account_ref", (args.cutoff,),
        ).fetchall()
        references = sorted({row[0] for row in rows})
        labels = {label: f"A{references.index(ref) + 1:02d}" for ref, label in rows}
        connection.close()
        account_ids = {}
        for metadata_path in pathlib.Path("/srv/auth-token-server/data/accounts").glob("*/metadata.json"):
            metadata = json.loads(metadata_path.read_text())
            account_ids[metadata["account_id"]] = labels[metadata["label"]]
    paths = set()
    for root in pathlib.Path("/tmp").glob("paas-*"):
        for pattern in ("ws.auth-recovery-worker.log*", "ws.recovery-worker.log*", "queue-drainer.stderr.log*"):
            paths.update(root.glob(pattern))
    for root in ("/code/pitchai-cli-new/.pitchai-state", "/code/pitchai-cli-new-monitoring/.pitchai-state"):
        for pattern in ("*recovery*log*", "*drainer*log*"):
            paths.update(pathlib.Path(root).rglob(pattern))
    counts = collections.Counter()
    emit("recovery_manifest", cell=args.cell, cutoff=args.cutoff, discovered_paths=len(paths), schema=1)
    for path in sorted(paths):
        source = hashed(path)
        count = 0
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", errors="replace") as stream:
            for number, line in enumerate(stream, start=1):
                if "HTTP 409:" not in line:
                    continue
                counts["candidate_lines"] += 1
                try:
                    response, _ = json.JSONDecoder().raw_decode(line.split("HTTP 409:", 1)[1].lstrip())
                except ValueError:
                    counts["invalid_json"] += 1
                    continue
                if not isinstance(response, dict) or not isinstance(response.get("accounts"), list):
                    counts["not_account_response"] += 1
                    continue
                match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", line[:150])
                log_time = match.group(0) if match else None
                if log_time and log_time >= args.cutoff:
                    continue
                for item in response["accounts"]:
                    label_alias = labels.get(item.get("label"))
                    id_alias = account_ids.get(item.get("account_id"))
                    if label_alias and id_alias and label_alias != id_alias:
                        raise ValueError("Historical account label and stable ID disagree")
                    account = id_alias or label_alias
                    if account is None:
                        counts["unmapped_account"] += 1
                        continue
                    if id_alias and not label_alias:
                        counts["renamed_label_resolved_by_stable_id"] += 1
                    observed_at = item.get("last_probe_at")
                    if observed_at and observed_at >= args.cutoff:
                        continue
                    usage = item.get("usage") or {}
                    record = {
                        "account": account, "provider_observed_at": observed_at,
                        "primary": window(usage.get("primary_window")),
                        "secondary": window(usage.get("secondary_window")),
                        "plan_type": usage.get("plan_type"),
                        "rate_limit_allowed": usage.get("rate_limit_allowed"),
                        "rate_limit_reached": usage.get("rate_limit_reached"),
                    }
                    emit("recovery_quota", source=source, line=number, log_time=log_time,
                         observation_key=hashed(json.dumps(record, sort_keys=True)), **record)
                    count += 1
                    for lease in item.get("active_sessions", []):
                        emit("lease_observation", source=source, line=number, log_time=log_time,
                             account=account,
                             affinity=hashed(lease.get("affinity_key")),
                             client=hashed(lease.get("client_name")),
                             issued_at=lease.get("issued_at"), expires_at=lease.get("expires_at"))
        emit("recovery_source", source=source, size_bytes=path.stat().st_size, quota_rows=count)
        counts["quota_rows"] += count
    emit("recovery_complete", discovered_paths=len(paths), **counts)


if __name__ == "__main__":
    main()
