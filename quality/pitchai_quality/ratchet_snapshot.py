# Copyright (c) 2026 PitchAI. All rights reserved.
"""Collect deterministic machine-readable quality debt snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio

from pitchai_quality.ratchet_commands import run_gate, tool_versions
from pitchai_quality.ratchet_model import gate_payload, sha256_bytes
from pitchai_quality.ratchet_parsers import parse_gate

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from pitchai_quality.ratchet_commands import GateRun, QualityProfile
    from pitchai_quality.ratchet_model import JsonValue


async def _git(root: Path, *arguments: str) -> str:
    completed = await anyio.run_process(("git", "-C", str(root), *arguments), check=True)
    return completed.stdout.decode().strip()


def _policy_paths(profile: QualityProfile) -> tuple[Path, ...]:
    if profile.custom_package:
        relative_paths = (
            ".github/workflows/python-strict.yml",
            "QUALITY.md",
            "quality/.semgrep.yml",
            "quality/.semgrepignore",
            "quality/pyproject.toml",
            "quality/uv.lock",
        )
    else:
        relative_paths = (
            ".github/workflows/python-strict.yml",
            ".semgrep.yml",
            "pyproject.toml",
            "scripts/check.py",
            "scripts/check_nested_event_loops.py",
            "scripts/check_no_dense_inline_comprehensions.py",
            "scripts/check_no_pure_wrapper_functions.py",
            "scripts/check_no_single_use_one_line_functions.py",
            "scripts/check_no_vague_signatures.py",
            "uv.lock",
        )
    return tuple(profile.root / relative for relative in relative_paths)


def _digests(root: Path, paths: Iterable[Path]) -> dict[str, JsonValue]:
    digests: dict[str, JsonValue] = {}
    for path in paths:
        if not path.is_file():
            message = f"snapshot policy file is missing: {path}"
            raise FileNotFoundError(message)
        relative = path.relative_to(root).as_posix()
        digests[relative] = sha256_bytes(path.read_bytes())
    return digests


def _normalized_command(root: Path, command: tuple[str, ...]) -> list[JsonValue]:
    root_text = str(root)
    return [part.replace(root_text, "<SOURCE_ROOT>") for part in command]


def _gate_record(profile: QualityProfile, run: GateRun) -> dict[str, JsonValue]:
    parsed = parse_gate(
        run.name,
        run.stdout,
        run.stderr,
        root=profile.root,
        source_paths=profile.runtime_files,
    )
    payload = gate_payload(profile.root, name=run.name, return_code=run.return_code, parsed=parsed)
    violation_count = payload["violation_count"]
    if not isinstance(violation_count, int):
        message = "gate violation count must be an integer"
        raise TypeError(message)
    if run.return_code != 0 and violation_count == 0:
        message = f"{run.name} failed without a parseable diagnostic"
        raise RuntimeError(message)
    if run.return_code == 0 and violation_count != 0:
        message = f"{run.name} returned success with {violation_count} diagnostic(s)"
        raise RuntimeError(message)
    payload["command"] = _normalized_command(profile.root, run.command)
    return payload


async def collect_snapshot(
    profile: QualityProfile,
    *,
    role: str,
    evidence_url: str | None,
) -> dict[str, JsonValue]:
    """Run every profile gate and return one deterministic snapshot payload.

    Returns:
        A deterministic JSON-compatible snapshot.
    """
    commit = await _git(profile.root, "rev-parse", "HEAD^{commit}")
    tree = await _git(profile.root, "rev-parse", "HEAD^{tree}")
    committed_at = await _git(profile.root, "show", "-s", "--format=%cI", "HEAD")
    records: list[JsonValue] = []
    for gate in profile.gates:
        records.extend((_gate_record(profile, await run_gate(profile, gate)),))
    source_files: list[JsonValue] = [path.relative_to(profile.root).as_posix() for path in profile.python_files]
    payload: dict[str, JsonValue] = {
        "committed_at": committed_at,
        "gate_count": len(records),
        "gates": records,
        "policy_sha256": _digests(profile.root, _policy_paths(profile)),
        "profile": "current-ten-gate" if profile.custom_package else "historical-nine-gate",
        "role": role,
        "schema": 1,
        "source_commit": commit,
        "source_file_count": len(source_files),
        "source_files": source_files,
        "source_tree": tree,
        "tool_versions": dict(await tool_versions(profile)),
    }
    if evidence_url is not None:
        payload["evidence_url"] = evidence_url
    return payload
