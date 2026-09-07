# Copyright (c) 2026 PitchAI. All rights reserved.
"""Corroborate frozen rollout paths with historical broker affinity strings.

Read only structured HTTP-409 account responses in existing recovery logs.
Emit exact hashes when an affinity equals client_name + ':' + a frozen source's
managed state directory. Neither client names, paths nor account data leave the
process. A match establishes source affinity, not continuous lease occupancy.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator


def emit(kind: str, **fields: object) -> None:
    """Write a compact allowlisted result; no raw log object is emitted."""
    sys.stdout.write(json.dumps({"kind": kind, **fields}, sort_keys=True) + "\n")


def optional_string(value: object) -> str | None:
    """Keep strings without coercing unexpected identity fields.

    Returns:
        An exact string or explicit missingness.
    """
    return value if isinstance(value, str) else None


def digest(value: str) -> str:
    """Hash an exact identifier without normalization.

    Returns:
        A SHA-256 hexadecimal digest.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def recovery_paths(runtime_root: Path) -> list[Path]:
    """Use the same source locations as the retained recovery extractor.

    Returns:
        Sorted distinct existing log paths.
    """
    paths: set[Path] = set()
    for root in runtime_root.glob("paas-*"):
        for pattern in ("ws.auth-recovery-worker.log*", "ws.recovery-worker.log*", "queue-drainer.stderr.log*"):
            paths.update(root.glob(pattern))
    for name in ("/code/pitchai-cli-new/.pitchai-state", "/code/pitchai-cli-new-monitoring/.pitchai-state"):
        for pattern in ("*recovery*log*", "*drainer*log*"):
            paths.update(Path(name).rglob(pattern))
    return sorted(paths)


def leases(path: Path, counts: Counter[str]) -> Iterator[dict[str, object]]:
    """Yield structured lease fields without retaining or logging raw text.

    Yields:
        One lease object from a broker account response.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", errors="replace") as stream:
        for line in stream:
            if "HTTP 409:" not in line:
                continue
            counts["candidate_lines"] += 1
            try:
                value, _ = cast("tuple[object, int]", json.JSONDecoder().raw_decode(
                    line.split("HTTP 409:", 1)[1].lstrip(),
                ))
            except ValueError:
                counts["invalid_json"] += 1
                continue
            if not isinstance(value, dict):
                continue
            response = cast("dict[str, object]", value)
            accounts = cast("list[dict[str, object]]", response.get("accounts", []))
            for account in accounts:
                yield from cast("list[dict[str, object]]", account.get("active_sessions", []))


def matching_links(lease: dict[str, object], states: dict[str, set[str]], cutoff: str,
                   counts: Counter[str]) -> set[tuple[str, str, str]]:
    """Require the exact recorded client/state convention before joining a source.

    Returns:
        Anonymous links, or an empty set with a counted exclusion.
    """
    client = optional_string(lease.get("client_name"))
    affinity, issued = optional_string(lease.get("affinity_key")), optional_string(lease.get("issued_at"))
    if not client or not affinity or not issued or issued >= cutoff:
        counts["missing_identity_or_outside_cutoff"] += 1
        return set()
    state = affinity.removeprefix(client + ":")
    if affinity == client + ":" + state and state in states:
        counts["matching_lease_occurrences"] += 1
        return {(source, digest(affinity), digest(client)) for source in states[state]}
    counts["no_frozen_managed_state_match"] += 1
    return set()


def main() -> None:
    """Match exact historical affinities against the original private source map.

    Raises:
        ValueError: If a source hash does not match its private path.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    cell = cast("str", args.cell)
    cutoff = cast("str", args.cutoff)
    raw = cast("Path", args.source_map).read_bytes()
    states: defaultdict[str, set[str]] = defaultdict(set)
    for source, path in cast("dict[str, str]", json.loads(raw)).items():
        if digest(path) != source:
            message = "Frozen source-map hash does not match its exact path"
            raise ValueError(message)
        if "/codex-home/sessions/" in path:
            states[path.split("/codex-home/sessions/", 1)[0]].add(source)
    paths, counts = recovery_paths(cast("Path", args.runtime_root)), Counter[str]()
    links: set[tuple[str, str, str]] = set()
    for path in paths:
        for lease in leases(path, counts):
            links.update(matching_links(lease, states, cutoff, counts))
    emit("affinity_manifest", cell=cell, cutoff=cutoff, source_map_sha256=digest(raw.decode()),
         source_states=len(states), recovery_paths=len(paths))
    for source, affinity, client in sorted(links):
        emit("source_affinity", source=source, affinity=affinity, client=client)
    emit("affinity_complete", counts=dict(counts), links=len(links))


if __name__ == "__main__":
    main()
