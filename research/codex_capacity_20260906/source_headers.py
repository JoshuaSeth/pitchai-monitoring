# Copyright (c) 2026 PitchAI. All rights reserved.
"""Extract anonymous source headers from an existing private source map.

Only the first two bounded lines are inspected. No paths or conversation text
are emitted. A matching outer session is provenance evidence, not proof that a
request was live or that its timestamp survived an import. This later capture
cannot retroactively certify the frozen usage extraction's original file prefix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .input_boundary import InputFailure

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

type Json = str | int | float | bool | Sequence[Json] | Mapping[str, Json] | None

_LINE_LIMIT = 262_144
_LINES = 2


def emit(kind: str, **fields: Json) -> None:
    """Emit one allowlisted JSON object."""
    sys.stdout.write(json.dumps({"kind": kind, **fields}, separators=(",", ":")) + "\n")


def optional_string(value: Json) -> str | None:
    """Keep strings and explicit missingness without coercing unexpected data.

    Returns:
        A string, or None for a missing or differently typed field.
    """
    return value if isinstance(value, str) else None


def parse_header(line: bytes) -> dict[str, str | None] | None:
    """Select session metadata, never a message or tool result.

    Returns:
        A hashed session ID and header timestamps/version, or None.
    """
    parsed = cast("Json", json.loads(line))
    if not isinstance(parsed, dict):
        return None
    event = parsed
    if event.get("type") != "session_meta":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    metadata = payload
    session = optional_string(metadata.get("id"))
    return {
        "event_at": optional_string(event.get("timestamp")),
        "session_created_at": optional_string(metadata.get("timestamp")),
        "session": hashlib.sha256(session.encode()).hexdigest() if session else None,
        "cli_version": optional_string(metadata.get("cli_version")),
    }


def read_headers(path: Path) -> tuple[list[dict[str, str | None]], str]:
    """Read a bounded prefix and report unavailable or malformed evidence.

    Returns:
        Parsed headers and an explicit read status.
    """
    headers: list[dict[str, str | None]] = []
    status = "not_read"
    with InputFailure((OSError, ValueError)) as failure:
        status = read_prefix(path, headers)
    if failure.error is not None:
        return headers, type(failure.error).__name__
    return headers, status


def read_prefix(path: Path, headers: list[dict[str, str | None]]) -> str:
    """Append metadata while retaining partial evidence if the next line fails.

    Returns:
        Successful read status or an explicit bounded-line status.
    """
    with path.open("rb") as stream:
        for _ in range(_LINES):
            line = stream.readline(_LINE_LIMIT)
            if not line:
                break
            if len(line) == _LINE_LIMIT and not line.endswith(b"\n"):
                return "line_limit_reached"
            header = parse_header(line)
            if header:
                headers.append(header)
    return "read"


def category(path: str) -> str:
    """Describe source location without certifying live execution.

    Returns:
        A coarse location category that does not expose the path.
    """
    if "/codex-home/sessions/" in path:
        return "managed_runtime"
    if "/.codex/sessions/" in path:
        return "cli_home"
    return "embedded_or_other"


def main() -> None:
    """Inspect only paths from the frozen input map; never rediscover new work.

    Raises:
        ValueError: If a source ID does not match its private path.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--cell", required=True)
    args = parser.parse_args()
    source_map = cast("Path", args.source_map)
    cell = cast("str", args.cell)
    raw = source_map.read_bytes()
    mapping = cast("dict[str, str]", json.loads(raw))
    emit("header_manifest", cell=cell, captured_at=datetime.now(UTC).isoformat(),
         source_map_sha256=hashlib.sha256(raw).hexdigest(), sources=len(mapping),
         prefix_limit_per_line=_LINE_LIMIT, lines_per_source=_LINES)
    counts: Counter[str] = Counter()
    for source, filename in sorted(mapping.items()):
        if hashlib.sha256(filename.encode()).hexdigest() != source:
            message = "The source map must pair exact path hashes with their original paths"
            raise ValueError(message)
        headers, status = read_headers(Path(filename))
        counts[status] += 1
        emit("source_header", source=source, category=category(filename), headers=headers, status=status)
    emit("header_complete", counts=dict(counts))


if __name__ == "__main__":
    main()
