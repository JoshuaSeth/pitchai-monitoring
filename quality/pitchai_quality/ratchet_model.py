# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed records and stable identities for Python quality debt snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_LINE_REFERENCE = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class DiagnosticSpan:
    """One source span reported by a quality checker."""

    path: str
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True)
class RawDiagnostic:
    """One checker diagnostic before stable identity calculation."""

    gate: str
    rule: str
    message: str
    span: DiagnosticSpan
    identity: str | None = None


@dataclass(frozen=True)
class ParsedGate:
    """Parsed diagnostics and metrics from one checker process."""

    diagnostics: tuple[RawDiagnostic, ...]
    metrics: Mapping[str, JsonValue]
    violation_count: int | None = None


def canonical_json(payload: JsonValue) -> str:
    """Serialize JSON deterministically for hashing and committed artifacts.

    Returns:
        Canonical, newline-terminated JSON text.
    """
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def sha256_bytes(content: bytes) -> str:
    """Return the lowercase SHA-256 digest for bytes."""
    digest = hashlib.sha256()
    digest.update(content)
    return digest.hexdigest()


def _relative_path(root: Path, raw_path: str) -> str:
    path = Path(raw_path)
    resolved = path.resolve(strict=False) if path.is_absolute() else (root / path).resolve(strict=False)
    if not resolved.is_relative_to(root):
        message = f"diagnostic path escapes source root: {raw_path}"
        raise ValueError(message)
    return resolved.relative_to(root).as_posix()


def _source_digest(root: Path, path: str, line: int) -> str:
    source_path = root / path
    source_lines = source_path.read_text(encoding="utf-8").splitlines()
    if line < 1 or line > len(source_lines):
        return sha256_bytes(b"")
    normalized = _WHITESPACE.sub(" ", source_lines[line - 1].strip())
    return sha256_bytes(normalized.encode())


def _normalized_message(message: str) -> str:
    without_line_numbers = _LINE_REFERENCE.sub("line <line>", message)
    return _WHITESPACE.sub(" ", without_line_numbers.strip())


def _fingerprint(diagnostic: RawDiagnostic, source_digest: str) -> str:
    stable_identity = (
        diagnostic.identity
        if diagnostic.identity is not None
        else "\0".join((_normalized_message(diagnostic.message), source_digest))
    )
    identity = f"{diagnostic.gate}\0{diagnostic.rule}\0{stable_identity}"
    return sha256_bytes(identity.encode())


def diagnostic_payloads(root: Path, diagnostics: Iterable[RawDiagnostic]) -> list[JsonValue]:
    """Group diagnostics by move-stable fingerprint with explicit locations.

    Returns:
        Deterministically ordered diagnostic groups.

    Raises:
        TypeError: If an internal diagnostic group has an invalid shape.
    """
    grouped: dict[str, dict[str, JsonValue]] = {}
    ordered = sorted(
        diagnostics,
        key=lambda item: (
            item.gate,
            item.span.path,
            item.span.line,
            item.span.column,
            item.rule,
            item.message,
        ),
    )
    for diagnostic in ordered:
        span = diagnostic.span
        relative = _relative_path(root, span.path)
        source_digest = _source_digest(root, relative, span.line)
        fingerprint = _fingerprint(diagnostic, source_digest)
        location: dict[str, JsonValue] = {
            "column": span.column,
            "line": span.line,
            "owner": relative.split("/", maxsplit=1)[0] if "/" in relative else "repository-root",
            "path": relative,
            "source_sha256": source_digest,
        }
        if span.end_line is not None:
            location["end_line"] = span.end_line
        if span.end_column is not None:
            location["end_column"] = span.end_column
        existing = grouped.get(fingerprint)
        if existing is None:
            grouped[fingerprint] = {
                "fingerprint": fingerprint,
                "locations": [location],
                "message": _normalized_message(diagnostic.message),
                "rule": diagnostic.rule,
            }
            continue
        locations = existing["locations"]
        if not isinstance(locations, list):
            message = "diagnostic locations must be a list"
            raise TypeError(message)
        locations.append(location)
    return [grouped[fingerprint] for fingerprint in sorted(grouped)]


def _location_count(diagnostic: JsonValue) -> int:
    if not isinstance(diagnostic, dict):
        message = "diagnostic group must be an object"
        raise TypeError(message)
    locations = diagnostic.get("locations")
    if not isinstance(locations, list):
        message = "diagnostic locations must be a list"
        raise TypeError(message)
    return len(locations)


def gate_payload(
    root: Path,
    *,
    name: str,
    return_code: int,
    parsed: ParsedGate,
) -> dict[str, JsonValue]:
    """Build one deterministic gate record from parsed diagnostics.

    Returns:
        A deterministic JSON-compatible gate record.

    Raises:
        ValueError: If a parser supplies a negative violation count.

    """
    diagnostics = diagnostic_payloads(root, parsed.diagnostics)
    location_count = sum(_location_count(item) for item in diagnostics)
    violation_count = parsed.violation_count if parsed.violation_count is not None else location_count
    if violation_count < 0:
        message = "gate violation count may not be negative"
        raise ValueError(message)
    return {
        "diagnostics": diagnostics,
        "metrics": dict(parsed.metrics),
        "name": name,
        "return_code": return_code,
        "unique_fingerprint_count": len(diagnostics),
        "violation_count": violation_count,
    }
