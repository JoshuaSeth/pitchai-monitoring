# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compare a candidate quality snapshot with an immutable activation baseline."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pitchai_quality.ratchet_model import JsonValue


def _objects(value: JsonValue, description: str) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        message = f"{description} must be a JSON object array"
        raise TypeError(message)
    return [item for item in value if isinstance(item, dict)]


def _text(record: dict[str, JsonValue], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        message = f"{key} must be text"
        raise TypeError(message)
    return value


def _integer(record: dict[str, JsonValue], key: str) -> int:
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"{key} must be an integer"
        raise TypeError(message)
    return value


def _gates(snapshot: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    gates = _objects(snapshot.get("gates"), "snapshot gates")
    named = {_text(gate, "name"): gate for gate in gates}
    if len(named) != len(gates):
        message = "snapshot gate names must be unique"
        raise ValueError(message)
    return named


def _fingerprint_counts(gate: dict[str, JsonValue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for diagnostic in _objects(gate.get("diagnostics"), "gate diagnostics"):
        fingerprint = _text(diagnostic, "fingerprint")
        locations = _objects(diagnostic.get("locations"), "diagnostic locations")
        counts[fingerprint] = len(locations)
    return counts


def _changed_file_failures(gate: dict[str, JsonValue], changed: set[str]) -> list[str]:
    failures: list[str] = []
    gate_name = _text(gate, "name")
    for diagnostic in _objects(gate.get("diagnostics"), "gate diagnostics"):
        fingerprint = _text(diagnostic, "fingerprint")
        for location in _objects(diagnostic.get("locations"), "diagnostic locations"):
            path = _text(location, "path")
            if path in changed:
                line = _integer(location, "line")
                failures.append(f"{gate_name}: changed file is not clean: {path}:{line} ({fingerprint})")
    return failures


def _gate_failures(
    baseline_gate: dict[str, JsonValue],
    candidate_gate: dict[str, JsonValue],
    changed: set[str],
) -> list[str]:
    gate_name = _text(baseline_gate, "name")
    baseline_total = _integer(baseline_gate, "violation_count")
    candidate_total = _integer(candidate_gate, "violation_count")
    failures: list[str] = []
    if candidate_total > baseline_total:
        failures.append(f"{gate_name}: violation count increased {baseline_total} -> {candidate_total}")
    baseline_counts = _fingerprint_counts(baseline_gate)
    candidate_counts = _fingerprint_counts(candidate_gate)
    for fingerprint, count in sorted(candidate_counts.items()):
        baseline_count = baseline_counts.get(fingerprint, 0)
        if baseline_count == 0:
            failures.append(f"{gate_name}: new fingerprint {fingerprint}")
        elif count > baseline_count:
            failures.append(
                f"{gate_name}: fingerprint multiplicity increased {baseline_count} -> {count}: {fingerprint}",
            )
    failures.extend(_changed_file_failures(candidate_gate, changed))
    return failures


def verify_snapshots(
    baseline: dict[str, JsonValue],
    candidate: dict[str, JsonValue],
    changed_python_files: Iterable[str],
) -> tuple[str, ...]:
    """Return every no-regression contract failure in deterministic order.

    Returns:
        Sorted contract failures, or an empty tuple when the ratchet passes.

    Raises:
        ValueError: If either snapshot violates the activation contract.
    """
    if baseline.get("role") != "activation":
        message = "ratchet baseline role must be activation"
        raise ValueError(message)
    baseline_gates = _gates(baseline)
    candidate_gates = _gates(candidate)
    if set(candidate_gates) != set(baseline_gates):
        message = "candidate gate set differs from activation baseline"
        raise ValueError(message)
    failures: list[str] = []
    changed = set(changed_python_files)
    for gate_name in sorted(baseline_gates):
        failures.extend(_gate_failures(baseline_gates[gate_name], candidate_gates[gate_name], changed))
    return tuple(sorted(failures))
