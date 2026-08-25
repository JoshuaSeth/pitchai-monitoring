# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse Pylint JSON while stabilizing duplicate-code ownership."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pitchai_quality.ratchet_json import decode_json, expect_array, expect_integer, expect_object, expect_text
from pitchai_quality.ratchet_model import DiagnosticSpan, ParsedGate, RawDiagnostic

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from pitchai_quality.ratchet_model import JsonValue

_DUPLICATE_PARTICIPANT = re.compile(
    r"^==(?P<module>[^:]+):\[(?P<start>\d+):(?P<end>\d+)\]$",
)
_MIN_DUPLICATE_PARTICIPANTS = 2


def _module_name(root: Path, source_path: Path) -> str:
    relative_path = source_path.resolve(strict=True).relative_to(root)
    module_parts = [] if relative_path.name == "__init__.py" else [relative_path.stem]
    parent = source_path.parent
    while parent != root and (parent / "__init__.py").is_file():
        module_parts.append(parent.name)
        parent = parent.parent
    return ".".join(reversed(module_parts))


def _module_paths(
    root: Path,
    source_paths: Iterable[Path],
    items: Iterable[dict[str, JsonValue]],
) -> dict[str, tuple[str, ...]]:
    indexed: dict[str, set[str]] = {}
    for source_path in source_paths:
        relative_path = source_path.resolve(strict=True).relative_to(root)
        relative = relative_path.as_posix()
        module = _module_name(root, source_path)
        indexed.setdefault(module, set()).add(relative)
    for item in items:
        module = item.get("module")
        path = item.get("path")
        if isinstance(module, str) and isinstance(path, str):
            indexed.setdefault(module, set()).add(path)
    return {module: tuple(sorted(paths)) for module, paths in indexed.items()}


def _duplicate_diagnostics(
    item: dict[str, JsonValue],
    module_paths: dict[str, tuple[str, ...]],
) -> tuple[RawDiagnostic, ...]:
    participants = _duplicate_participants(item)
    module_names: list[str] = []
    for module, _start, _end in participants:
        module_names.append(module)
    modules = tuple(sorted(module_names))
    identity = f"duplicate-code:{'|'.join(modules)}"
    stable_message = f"Similar lines in {len(participants)} files: {', '.join(modules)}"
    diagnostics: list[RawDiagnostic] = []
    for module, start, end in participants:
        paths = module_paths.get(module, ())
        if not paths:
            failure = f"pylint duplicate-code participant cannot be mapped to source: {module}"
            raise RuntimeError(failure)
        diagnostics.extend(
            RawDiagnostic(
                gate="pylint",
                rule="R0801",
                message=stable_message,
                span=DiagnosticSpan(path=path, line=start + 1, column=1, end_line=end),
                identity=identity,
            )
            for path in paths
        )
    return tuple(diagnostics)


def _duplicate_participants(item: dict[str, JsonValue]) -> tuple[tuple[str, int, int], ...]:
    message = expect_text(item.get("message"), "pylint duplicate-code message")
    participants: list[tuple[str, int, int]] = []
    for line in message.splitlines():
        match = _DUPLICATE_PARTICIPANT.fullmatch(line)
        if match is not None:
            participants.append(
                (match.group("module"), int(match.group("start")), int(match.group("end"))),
            )
    if len(participants) < _MIN_DUPLICATE_PARTICIPANTS:
        failure = "pylint duplicate-code diagnostic has no complete participant list"
        raise RuntimeError(failure)
    return tuple(participants)


def _standard_diagnostic(item: dict[str, JsonValue], rule: str) -> RawDiagnostic:
    end_line_value = item.get("endLine")
    end_column_value = item.get("endColumn")
    end_line = end_line_value if isinstance(end_line_value, int) and not isinstance(end_line_value, bool) else None
    end_column = (
        end_column_value + 1 if isinstance(end_column_value, int) and not isinstance(end_column_value, bool) else None
    )
    span = DiagnosticSpan(
        path=expect_text(item.get("path"), "pylint path"),
        line=expect_integer(item.get("line"), "pylint line"),
        column=expect_integer(item.get("column"), "pylint column", offset=1),
        end_line=end_line,
        end_column=end_column,
    )
    return RawDiagnostic(
        gate="pylint",
        rule=rule,
        message=expect_text(item.get("message"), "pylint message"),
        span=span,
    )


def parse_pylint(output: bytes, *, root: Path, source_paths: Iterable[Path]) -> ParsedGate:
    """Parse Pylint JSON2 with stable duplicate-code participants.

    Returns:
        Parsed Pylint diagnostics and score.

    Raises:
        TypeError: If the Pylint score is not numeric.
    """
    payload = expect_object(decode_json(output), "pylint output")
    raw_items = expect_array(payload.get("messages"), "pylint messages")
    items: list[dict[str, JsonValue]] = []
    for raw_item in raw_items:
        item = expect_object(raw_item, "pylint diagnostic")
        items.append(item)
    module_paths = _module_paths(root, source_paths, items)
    diagnostics: list[RawDiagnostic] = []
    for item in items:
        rule = expect_text(item.get("messageId"), "pylint message id")
        if rule == "R0801":
            diagnostics.extend(_duplicate_diagnostics(item, module_paths))
            continue
        diagnostics.append(_standard_diagnostic(item, rule))
    statistics = expect_object(payload.get("statistics"), "pylint statistics")
    score = statistics.get("score")
    if not isinstance(score, int | float) or isinstance(score, bool):
        message = "pylint score must be numeric"
        raise TypeError(message)
    return ParsedGate(tuple(diagnostics), {"score": float(score)}, violation_count=len(items))
