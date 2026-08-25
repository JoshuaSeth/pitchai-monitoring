# Copyright (c) 2026 PitchAI. All rights reserved.
"""Behavior tests for immutable quality identities and ratchet enforcement."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from pitchai_quality.ratchet_event import comparison_base
from pitchai_quality.ratchet_model import DiagnosticSpan, RawDiagnostic, diagnostic_payloads
from pitchai_quality.ratchet_pylint import parse_pylint
from pitchai_quality.ratchet_verify import verify_snapshots

if TYPE_CHECKING:
    from pitchai_quality.ratchet_model import JsonValue


def _location(path: str) -> dict[str, JsonValue]:
    return {
        "column": 1,
        "line": 1,
        "owner": path.split("/", maxsplit=1)[0],
        "path": path,
        "source_sha256": "source",
    }


def _gate(name: str, fingerprints: tuple[tuple[str, tuple[str, ...]], ...]) -> dict[str, JsonValue]:
    diagnostics: list[JsonValue] = []
    violation_count = 0
    for fingerprint, paths in fingerprints:
        locations: list[JsonValue] = [_location(path) for path in paths]
        diagnostics.append(
            {
                "fingerprint": fingerprint,
                "locations": locations,
                "message": "diagnostic",
                "rule": "RULE",
            },
        )
        violation_count += len(locations)
    return {
        "diagnostics": diagnostics,
        "metrics": {},
        "name": name,
        "return_code": 1 if violation_count else 0,
        "unique_fingerprint_count": len(diagnostics),
        "violation_count": violation_count,
    }


def _snapshot(role: str, gate: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {"gates": [gate], "role": role}


def _fingerprint(payloads: list[JsonValue]) -> str:
    if len(payloads) != 1 or not isinstance(payloads[0], dict):
        message = "expected exactly one diagnostic group"
        raise AssertionError(message)
    value = payloads[0].get("fingerprint")
    if not isinstance(value, str):
        message = "diagnostic fingerprint must be text"
        raise TypeError(message)
    return value


_ACTIVATION = _snapshot("activation", _gate("ruff", (("known", ("legacy.py",)),)))
_ACTIVATION_SHA = "a" * 40


def _pylint_duplicate_output(excerpt: str) -> bytes:
    payload = {
        "messages": [
            {
                "column": 0,
                "endColumn": None,
                "endLine": None,
                "line": 1,
                "message": f"Similar lines in 2 files\n==first:[0:2]\n==second:[0:2]\n{excerpt}",
                "messageId": "R0801",
                "module": "second",
                "path": "second.py",
            },
        ],
        "statistics": {"score": 9.0},
    }
    return json.dumps(payload).encode()


def _expect_equal[ValueT](actual: ValueT, expected: ValueT, message: str) -> None:
    if actual != expected:
        raise AssertionError(message)


def _expect_contains(needle: str, haystack: str) -> None:
    if needle not in haystack:
        message = f"expected text is missing: {needle}"
        raise AssertionError(message)


def test_fingerprint_is_path_and_line_independent() -> None:
    """Keep identity stable when the same source line moves."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first_path = root / "first.py"
        moved_path = root / "nested" / "moved.py"
        moved_path.parent.mkdir()
        first_path.write_text("result = risky_call()\n", encoding="utf-8")
        moved_path.write_text("\n\nresult = risky_call()\n", encoding="utf-8")
        first = RawDiagnostic(
            gate="ruff",
            rule="RULE",
            message="problem at line 1",
            span=DiagnosticSpan(str(first_path), 1, 1),
        )
        moved = RawDiagnostic(
            gate="ruff",
            rule="RULE",
            message="problem at line 3",
            span=DiagnosticSpan(str(moved_path), 3, 1),
        )

        first_fingerprint = _fingerprint(diagnostic_payloads(root, (first,)))
        moved_fingerprint = _fingerprint(diagnostic_payloads(root, (moved,)))

    _expect_equal(first_fingerprint, moved_fingerprint, "fingerprint changed after a source move")


def test_pylint_duplicate_identity_ignores_unstable_excerpt() -> None:
    """Own duplicate-code debt by its participants, not Pylint's unstable excerpt."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first_path = root / "first.py"
        second_path = root / "second.py"
        first_path.write_text("value = 1\nresult = value\n", encoding="utf-8")
        second_path.write_text("value = 1\nresult = value\n", encoding="utf-8")
        source_paths = (first_path, second_path)
        first_parse = parse_pylint(
            _pylint_duplicate_output("first unstable excerpt"),
            root=root,
            source_paths=source_paths,
        )
        second_parse = parse_pylint(
            _pylint_duplicate_output("different unstable excerpt"),
            root=root,
            source_paths=source_paths,
        )

        first_payloads = diagnostic_payloads(root, first_parse.diagnostics)
        second_payloads = diagnostic_payloads(root, second_parse.diagnostics)

    _expect_equal(first_payloads, second_payloads, "Pylint's unstable excerpt changed the fingerprint")
    _expect_equal(first_parse.violation_count, 1, "raw Pylint violation count changed")
    serialized = json.dumps(first_payloads, sort_keys=True)
    _expect_contains('"path": "first.py"', serialized)
    _expect_contains('"path": "second.py"', serialized)


def test_unchanged_debt_passes() -> None:
    """Allow an unchanged fingerprint on an untouched source file."""
    candidate = _snapshot("candidate", _gate("ruff", (("known", ("legacy.py",)),)))

    failures = verify_snapshots(_ACTIVATION, candidate, ())

    _expect_equal(failures, (), "unchanged debt unexpectedly failed the ratchet")


def test_new_fingerprint_fails_without_a_count_increase() -> None:
    """Reject debt replacement even when the total stays flat."""
    candidate = _snapshot("candidate", _gate("ruff", (("new", ("other.py",)),)))

    failure_text = "\n".join(verify_snapshots(_ACTIVATION, candidate, ()))

    _expect_contains("new fingerprint new", failure_text)


def test_multiplicity_and_total_increases_fail() -> None:
    """Reject duplicate debt and the resulting aggregate regression."""
    candidate = _snapshot(
        "candidate",
        _gate("ruff", (("known", ("legacy.py", "copy.py")),)),
    )

    failure_text = "\n".join(verify_snapshots(_ACTIVATION, candidate, ()))

    _expect_contains("violation count increased 1 -> 2", failure_text)
    _expect_contains("fingerprint multiplicity increased 1 -> 2", failure_text)


def test_changed_file_must_be_clean() -> None:
    """Reject pre-existing debt that remains in a changed Python file."""
    candidate = _snapshot("candidate", _gate("ruff", (("known", ("legacy.py",)),)))

    failure_text = "\n".join(verify_snapshots(_ACTIVATION, candidate, ("legacy.py",)))

    _expect_contains("changed file is not clean: legacy.py:1", failure_text)


def test_pull_request_comparison_base() -> None:
    """Use the exact pull-request base commit."""
    base_sha = "b" * 40
    event: dict[str, JsonValue] = {"pull_request": {"base": {"sha": base_sha}}}

    resolved = comparison_base("pull_request", event, _ACTIVATION_SHA)

    _expect_equal(resolved, base_sha, "pull-request comparison base changed")


def test_initial_push_uses_activation_comparison_base() -> None:
    """Use the activation commit for an all-zero initial push base."""
    event: dict[str, JsonValue] = {"before": "0" * 40}

    resolved = comparison_base("push", event, _ACTIVATION_SHA)

    _expect_equal(resolved, _ACTIVATION_SHA, "initial push comparison base changed")


_TESTS = (
    test_fingerprint_is_path_and_line_independent,
    test_pylint_duplicate_identity_ignores_unstable_excerpt,
    test_unchanged_debt_passes,
    test_new_fingerprint_fails_without_a_count_increase,
    test_multiplicity_and_total_increases_fail,
    test_changed_file_must_be_clean,
    test_pull_request_comparison_base,
    test_initial_push_uses_activation_comparison_base,
)


def load_tests(
    _loader: unittest.TestLoader,
    _tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    """Expose function-style strict tests to the standard-library runner.

    Returns:
        The complete ratchet unit-test suite.
    """
    suite = unittest.TestSuite()
    for test in _TESTS:
        suite.addTest(unittest.FunctionTestCase(test))
    return suite
