# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse machine-readable checker output into quality diagnostics."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pitchai_quality.ratchet_json import decode_json, expect_array, expect_integer, expect_object, expect_text
from pitchai_quality.ratchet_model import DiagnosticSpan, ParsedGate, RawDiagnostic
from pitchai_quality.ratchet_pylint import parse_pylint

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from pitchai_quality.ratchet_model import JsonValue

_CUSTOM_DIAGNOSTIC = re.compile(
    r"^(?P<path>.+?\.(?:py|pyi|yml|yaml|toml|json|md)):(?P<line>\d+)"
    r"(?::(?P<column>\d+))?: (?P<message>.+)$",
)


def parse_custom(gate: str, stdout: bytes, stderr: bytes) -> ParsedGate:
    """Parse one repository-native checker output.

    Returns:
        Parsed custom-checker diagnostics.
    """
    diagnostics: list[RawDiagnostic] = []
    combined = b"\n".join((stdout, stderr)).decode(errors="strict")
    for line in combined.splitlines():
        match = _CUSTOM_DIAGNOSTIC.match(line)
        if match is None:
            continue
        message = match.group("message")
        rule = message.split(":", maxsplit=1)[0].strip().replace(" ", "-")
        diagnostics.append(
            RawDiagnostic(
                gate=gate,
                rule=rule,
                message=message,
                span=DiagnosticSpan(
                    path=match.group("path"),
                    line=int(match.group("line")),
                    column=int(match.group("column") or "1"),
                ),
            ),
        )
    return ParsedGate(tuple(diagnostics), {})


def parse_ruff(output: bytes) -> ParsedGate:
    """Parse Ruff's JSON output.

    Returns:
        Parsed Ruff diagnostics.
    """
    diagnostics: list[RawDiagnostic] = []
    for raw_item in expect_array(decode_json(output), "ruff output"):
        item = expect_object(raw_item, "ruff diagnostic")
        start = expect_object(item.get("location"), "ruff location")
        end = expect_object(item.get("end_location"), "ruff end location")
        diagnostics.append(
            RawDiagnostic(
                gate="ruff",
                rule=expect_text(item.get("code"), "ruff rule"),
                message=expect_text(item.get("message"), "ruff message"),
                span=DiagnosticSpan(
                    path=expect_text(item.get("filename"), "ruff filename"),
                    line=expect_integer(start.get("row"), "ruff row"),
                    column=expect_integer(start.get("column"), "ruff column"),
                    end_line=expect_integer(end.get("row"), "ruff end row"),
                    end_column=expect_integer(end.get("column"), "ruff end column"),
                ),
            ),
        )
    return ParsedGate(tuple(diagnostics), {})


def parse_basedpyright(output: bytes) -> ParsedGate:
    """Parse BasedPyright's JSON output, including fatal warnings.

    Returns:
        Parsed BasedPyright diagnostics and severity counts.
    """
    payload = expect_object(decode_json(output), "basedpyright output")
    diagnostics: list[RawDiagnostic] = []
    for raw_item in expect_array(payload.get("generalDiagnostics"), "basedpyright diagnostics"):
        item = expect_object(raw_item, "basedpyright diagnostic")
        range_value = expect_object(item.get("range"), "basedpyright range")
        start = expect_object(range_value.get("start"), "basedpyright start")
        end = expect_object(range_value.get("end"), "basedpyright end")
        severity = expect_text(item.get("severity"), "basedpyright severity")
        rule_value = item.get("rule")
        rule = rule_value if isinstance(rule_value, str) else severity
        diagnostics.append(
            RawDiagnostic(
                gate="basedpyright",
                rule=rule,
                message=expect_text(item.get("message"), "basedpyright message"),
                span=DiagnosticSpan(
                    path=expect_text(item.get("file"), "basedpyright file"),
                    line=expect_integer(start.get("line"), "basedpyright line", offset=1),
                    column=expect_integer(start.get("character"), "basedpyright column", offset=1),
                    end_line=expect_integer(end.get("line"), "basedpyright end line", offset=1),
                    end_column=expect_integer(end.get("character"), "basedpyright end column", offset=1),
                ),
            ),
        )
    summary = expect_object(payload.get("summary"), "basedpyright summary")
    metrics: dict[str, JsonValue] = {
        "errors": expect_integer(summary.get("errorCount"), "basedpyright error count"),
        "warnings": expect_integer(summary.get("warningCount"), "basedpyright warning count"),
    }
    return ParsedGate(tuple(diagnostics), metrics)


def parse_semgrep(output: bytes) -> ParsedGate:
    """Parse Semgrep JSON and reject engine errors.

    Returns:
        Parsed Semgrep diagnostics and engine version.

    Raises:
        RuntimeError: If Semgrep reports an engine error.
    """
    payload = expect_object(decode_json(output), "semgrep output")
    errors = expect_array(payload.get("errors"), "semgrep errors")
    if errors:
        message = f"semgrep reported {len(errors)} engine error(s)"
        raise RuntimeError(message)
    diagnostics: list[RawDiagnostic] = []
    for raw_item in expect_array(payload.get("results"), "semgrep results"):
        item = expect_object(raw_item, "semgrep diagnostic")
        start = expect_object(item.get("start"), "semgrep start")
        end = expect_object(item.get("end"), "semgrep end")
        extra = expect_object(item.get("extra"), "semgrep extra")
        diagnostics.append(
            RawDiagnostic(
                gate="semgrep",
                rule=expect_text(item.get("check_id"), "semgrep check id"),
                message=expect_text(extra.get("message"), "semgrep message"),
                span=DiagnosticSpan(
                    path=expect_text(item.get("path"), "semgrep path"),
                    line=expect_integer(start.get("line"), "semgrep line"),
                    column=expect_integer(start.get("col"), "semgrep column"),
                    end_line=expect_integer(end.get("line"), "semgrep end line"),
                    end_column=expect_integer(end.get("col"), "semgrep end column"),
                ),
            ),
        )
    version = payload.get("version")
    metrics: dict[str, JsonValue] = {"version": version if isinstance(version, str) else "unknown"}
    return ParsedGate(tuple(diagnostics), metrics)


def parse_gate(
    gate: str,
    stdout: bytes,
    stderr: bytes,
    *,
    root: Path | None = None,
    source_paths: Iterable[Path] = (),
) -> ParsedGate:
    """Dispatch one checker process to its strict parser.

    Returns:
        Parsed diagnostics for the selected gate.

    Raises:
        ValueError: If the gate has no registered parser.
    """
    if gate in {
        "no-validation-bypasses",
        "nested-event-loops",
        "no-vague-signatures",
        "no-single-use-one-line-functions",
        "no-pure-wrapper-functions",
        "no-dense-inline-comprehensions",
    }:
        return parse_custom(gate, stdout, stderr)
    if gate == "ruff":
        return parse_ruff(stdout)
    if gate == "basedpyright":
        return parse_basedpyright(stdout)
    if gate == "pylint":
        if root is None:
            message = "pylint parsing requires the source root"
            raise ValueError(message)
        return parse_pylint(stdout, root=root, source_paths=source_paths)
    if gate == "semgrep":
        return parse_semgrep(stdout)
    message = f"unsupported quality gate: {gate}"
    raise ValueError(message)
