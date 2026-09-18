# Copyright (c) 2026 PitchAI. All rights reserved.
"""Extract anonymous historical quota/lease evidence from broker recovery logs.

Run with Python 3.12. Decode only actual HTTP-409 JSON response objects. Never
retain log message text, credentials, account references, labels or client names.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .input_boundary import InputFailure

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

type Json = str | int | float | bool | Sequence[Json] | Mapping[str, Json] | None
type Record = dict[str, Json]


@dataclass
class Recovery:
    """Private identity resolution and counters shared across one extraction."""

    cutoff: str
    labels: dict[str | None, str]
    account_ids: dict[str | None, str]
    counts: collections.Counter[str]


def hashed(value: Json | Path) -> str:
    """Hash a private source or affinity value without retaining it.

    Returns:
        A deterministic SHA-256 hexadecimal digest.
    """
    return hashlib.sha256(str(value).encode()).hexdigest()


def emit(kind: str, **fields: Json) -> None:
    """Write one allowlisted record as deterministic compact JSON."""
    sys.stdout.write(json.dumps({"kind": kind, **fields}, sort_keys=True, separators=(",", ":")) + "\n")


def window(value: Json) -> Record | None:
    """Select the reported quota fields without interpreting their units.

    Returns:
        Four quota fields, or None when no window object was recorded.
    """
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in (
        "used_percent", "limit_window_seconds", "reset_at", "reset_after_seconds",
    )}


def identities(cutoff: str, alias_map: Path | None) -> Recovery:
    """Load aliases or resolve them privately from the durable broker store.

    Returns:
        Account mappings and empty extraction counters.
    """
    if alias_map:
        mapping = cast("dict[str, dict[str | None, str]]", json.loads(alias_map.read_text(encoding="utf-8")))
        return Recovery(cutoff, mapping["labels"], mapping["account_ids"], collections.Counter())
    with closing(sqlite3.connect(
        "file:/srv/codex-usage-dashboard/usage-history.sqlite3?mode=ro", uri=True,
    )) as connection:
        rows = cast("list[tuple[str, str]]", connection.execute(
            "SELECT DISTINCT account_ref, account_label FROM account_usage_samples "
            "WHERE sampled_at < ? ORDER BY account_ref", (cutoff,),
        ).fetchall())
    references = sorted({row[0] for row in rows})
    labels: dict[str | None, str] = {label: f"A{references.index(ref) + 1:02d}" for ref, label in rows}
    account_ids: dict[str | None, str] = {}
    for metadata_path in Path("/srv/auth-token-server/data/accounts").glob("*/metadata.json"):
        metadata = cast("dict[str, str]", json.loads(metadata_path.read_text(encoding="utf-8")))
        account_ids[metadata["account_id"]] = labels[metadata["label"]]
    return Recovery(cutoff, labels, account_ids, collections.Counter())


def discover_paths() -> list[Path]:
    """Find existing recovery and queue-drainer logs, including rotations.

    Returns:
        Every matching path once, in deterministic order.
    """
    paths: set[Path] = set()
    for root in Path(tempfile.gettempdir()).glob("paas-*"):
        for pattern in ("ws.auth-recovery-worker.log*", "ws.recovery-worker.log*", "queue-drainer.stderr.log*"):
            paths.update(root.glob(pattern))
    for root in ("/code/pitchai-cli-new/.pitchai-state", "/code/pitchai-cli-new-monitoring/.pitchai-state"):
        for pattern in ("*recovery*log*", "*drainer*log*"):
            paths.update(Path(root).rglob(pattern))
    return sorted(paths)


def response_accounts(line: str, counts: collections.Counter[str]) -> list[Record] | None:
    """Decode actual HTTP-409 account responses and count invalid candidates.

    Returns:
        The recorded account list, or None for irrelevant or invalid lines.
    """
    if "HTTP 409:" not in line:
        return None
    counts["candidate_lines"] += 1
    decoded: tuple[Json, int] = (None, 0)
    with InputFailure(ValueError) as failure:
        decoded = cast("tuple[Json, int]", json.JSONDecoder().raw_decode(line.split("HTTP 409:", 1)[1].lstrip()))
    if failure.error is not None:
        counts["invalid_json"] += 1
        return None
    response = decoded[0]
    if not isinstance(response, dict) or not isinstance(response.get("accounts"), list):
        counts["not_account_response"] += 1
        return None
    return cast("list[Record]", response["accounts"])


def extract_account(item: Record, context: Recovery, location: Record) -> int:
    """Resolve one historical account and export its quota and lease evidence.

    Returns:
        One when the quota row was emitted, otherwise zero.

    Raises:
        ValueError: A recorded stable ID and label identify different accounts.
    """
    label_alias = context.labels.get(cast("str | None", item.get("label")))
    id_alias = context.account_ids.get(cast("str | None", item.get("account_id")))
    if label_alias and id_alias and label_alias != id_alias:
        message = "Historical account label and stable ID disagree"
        raise ValueError(message)
    account = id_alias or label_alias
    if account is None:
        context.counts["unmapped_account"] += 1
        return 0
    if id_alias and not label_alias:
        context.counts["renamed_label_resolved_by_stable_id"] += 1
    observed_at = cast("str | None", item.get("last_probe_at"))
    if observed_at and observed_at >= context.cutoff:
        return 0
    usage = cast("Record", item.get("usage") or {})
    record: Record = {
        "account": account, "provider_observed_at": observed_at,
        "primary": window(usage.get("primary_window")), "secondary": window(usage.get("secondary_window")),
        "plan_type": usage.get("plan_type"), "rate_limit_allowed": usage.get("rate_limit_allowed"),
        "rate_limit_reached": usage.get("rate_limit_reached"),
    }
    emit("recovery_quota", **location, observation_key=hashed(json.dumps(record, sort_keys=True)), **record)
    for lease in cast("list[Record]", item.get("active_sessions", [])):
        emit("lease_observation", **location, account=account,
             affinity=hashed(lease.get("affinity_key")), client=hashed(lease.get("client_name")),
             issued_at=lease.get("issued_at"), expires_at=lease.get("expires_at"))
    return 1


def extract_file(path: Path, context: Recovery) -> None:
    """Stream one existing log and retain its source count even when empty."""
    source = hashed(path)
    count = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream, start=1):
            accounts = response_accounts(line, context.counts)
            if accounts is None:
                continue
            match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", line[:150])
            log_time = match.group(0) if match else None
            if log_time and log_time >= context.cutoff:
                continue
            location: Record = {"source": source, "line": number, "log_time": log_time}
            for item in accounts:
                count += extract_account(item, context, location)
    emit("recovery_source", source=source, size_bytes=path.stat().st_size, quota_rows=count)
    context.counts["quota_rows"] += count


def main() -> None:
    """Export existing recovery histories with explicit inventory and completion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--alias-map", type=Path)
    parser.add_argument("--cell", default="dev-main-and-monitoring")
    args = parser.parse_args()
    context = identities(cast("str", args.cutoff), cast("Path | None", args.alias_map))
    paths = discover_paths()
    emit("recovery_manifest", cell=cast("str", args.cell), cutoff=context.cutoff, discovered_paths=len(paths), schema=1)
    for path in paths:
        extract_file(path, context)
    emit("recovery_complete", discovered_paths=len(paths), **context.counts)


if __name__ == "__main__":
    main()
