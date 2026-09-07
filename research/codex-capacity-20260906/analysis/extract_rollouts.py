# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stream allowlisted token and rate-limit observations from existing rollouts.

Run with Python 3.12 from the repository root using
``-m research.codex-capacity-20260906.analysis.extract_rollouts``. Inputs are existing
search indexes and explicitly named session roots. File size is frozen before
each read; event timestamps additionally obey a UTC cutoff. No prompts, answers,
tool payloads, instructions, account IDs or paths are emitted. Repeated events
remain candidates for the separate global deduplication stage.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .rollout_events import Context, digest, emit

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .rollout_events import Record

PROGRESS_INTERVAL = 500


def read_prefix(path: Path, cell: str, cutoff: datetime.datetime, stats: Counter[str]) -> Record:
    """Read the frozen byte prefix and report concurrent source changes.

    Returns:
        Source size, time coverage and the exact prefix digest.
    """
    before = path.stat()
    source = digest(str(path))
    content_hash = hashlib.sha256()
    context = Context(stats=stats)
    with path.open("rb") as stream:
        while stream.tell() < before.st_size:
            offset = stream.tell()
            line = stream.readline(before.st_size - offset)
            content_hash.update(line)
            stats["bytes"] += len(line)
            stats["lines"] += 1
            fields = context.accept(line, cutoff)
            if fields is not None:
                emit("token_event", cell=cell, source=source, offset=offset, **fields)
    after = path.stat()
    status = "read"
    if after.st_size < before.st_size:
        status = "source_shrank_during_read"
    elif after.st_mtime_ns != before.st_mtime_ns and after.st_size == before.st_size:
        status = "source_rewritten_during_read"
    return {"status": status, "initial_bytes": before.st_size, "final_bytes": after.st_size,
            "first_at": context.first_at, "last_at": context.last_at, "prefix_sha256": content_hash.hexdigest()}


def scan(path: Path, cell: str, cutoff: datetime.datetime) -> None:
    """Export one source and retain read failures as explicit missingness."""
    stats: Counter[str] = Counter()
    try:
        source_fields = read_prefix(path, cell, cutoff, stats)
    except (OSError, ValueError) as error:
        source_fields = {"status": type(error).__name__}
    emit("rollout_source", cell=cell, source=digest(str(path)), **source_fields, **stats)


def discover(indexes: list[str], roots: list[str]) -> set[Path]:
    """Combine indexed and explicitly named rollout locations.

    Returns:
        Every matching source path once.
    """
    paths: set[Path] = set()
    for name in indexes:
        with closing(sqlite3.connect(f"file:{name}?mode=ro", uri=True)) as connection:
            rows = cast("Iterator[tuple[str]]", connection.execute("SELECT path FROM rollout_files"))
            paths.update(Path(row[0]) for row in rows)
    for pattern in roots:
        base = Path(Path(pattern).anchor or ".")
        for root in base.glob(str(Path(pattern).relative_to(base))):
            paths.update(root.rglob("*.jsonl"))
    return paths


def private_map(paths: set[Path], destination: Path) -> None:
    """Write the optional source crosswalk with owner-only file permissions."""
    with open(destination, "w", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump({digest(str(path)): str(path) for path in paths}, stream, sort_keys=True)


def scan_paths(paths: set[Path], cell: str, cutoff: datetime.datetime) -> None:
    """Read each inode once, retaining path aliases and unreadable sources."""
    inodes: dict[tuple[int, int], str] = {}
    for number, path in enumerate(sorted(paths), start=1):
        try:
            stat = path.stat()
        except OSError:
            scan(path, cell, cutoff)
            continue
        identity = (stat.st_dev, stat.st_ino)
        if identity in inodes:
            emit("rollout_alias", cell=cell, source=digest(str(path)),
                 canonical_source=inodes[identity], reason="same_device_and_inode")
            continue
        inodes[identity] = digest(str(path))
        scan(path, cell, cutoff)
        if number % PROGRESS_INTERVAL == 0:
            sys.stderr.write(f"{cell}: scanned {number}/{len(paths)} paths\n")


def main() -> None:
    """Export existing rollouts with inventory and final completion records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--index", action="append", default=[])
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--private-source-map", type=Path)
    args = parser.parse_args()
    cell = cast("str", args.cell)
    cutoff_text = cast("str", args.cutoff)
    cutoff = datetime.datetime.fromisoformat(cutoff_text)
    paths = discover(cast("list[str]", args.index), cast("list[str]", args.root))
    destination = cast("Path | None", args.private_source_map)
    if destination:
        private_map(paths, destination)
    emit("rollout_manifest", cell=cell, cutoff=cutoff_text, discovered_paths=len(paths),
         schema=1, extracted_at=datetime.datetime.now(datetime.UTC).isoformat())
    scan_paths(paths, cell, cutoff)
    emit("rollout_complete", cell=cell, discovered_paths=len(paths))


if __name__ == "__main__":
    main()
