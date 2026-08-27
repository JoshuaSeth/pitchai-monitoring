# Copyright (c) 2026 PitchAI. All rights reserved.
"""Create and enforce immutable Python quality debt snapshots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio

from pitchai_quality.ratchet_commands import current_profile, historical_profile
from pitchai_quality.ratchet_event import comparison_base, validate_commit_sha
from pitchai_quality.ratchet_model import canonical_json
from pitchai_quality.ratchet_snapshot import collect_snapshot
from pitchai_quality.ratchet_verify import verify_snapshots

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pitchai_quality.ratchet_model import JsonValue


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or verify a complete quality debt snapshot.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot", help="Run every gate and write a deterministic JSON snapshot.")
    snapshot.add_argument("--profile", choices=("current", "historical"), required=True)
    snapshot.add_argument("--root", type=Path, required=True)
    snapshot.add_argument("--role", choices=("historical", "activation", "candidate"), required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--expect-commit", required=True)
    snapshot.add_argument("--expect-tree", required=True)
    snapshot.add_argument("--evidence-url")
    verify = subparsers.add_parser("verify", help="Enforce an activation snapshot against the current checkout.")
    verify.add_argument("--baseline", type=Path, required=True)
    verify.add_argument(
        "--base",
        required=True,
        help="Full Git base SHA, or 'github-event' to resolve the current Actions event.",
    )
    verify.add_argument("--candidate-report", type=Path)
    return parser


def _json_object(path: Path) -> dict[str, JsonValue]:
    value = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        message = f"snapshot must be a JSON object: {path}"
        raise TypeError(message)
    return value


async def _git(root: Path, *arguments: str) -> str:
    completed = await anyio.run_process(("git", "-C", str(root), *arguments), check=True)
    return completed.stdout.decode().strip()


async def _is_ancestor(root: Path, ancestor: str) -> bool:
    completed = await anyio.run_process(
        ("git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, "HEAD"),
        check=False,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    message = f"git merge-base --is-ancestor failed with status {completed.returncode}"
    raise RuntimeError(message)


async def _python_files_changed_since(root: Path, base: str) -> frozenset[str]:
    output = await _git(
        root,
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        f"{base}...HEAD",
        "--",
        "*.py",
        "*.pyi",
    )
    return frozenset(filter(None, output.split("\0")))


async def _changed_python_files(root: Path, base: str, activation: str) -> tuple[str, ...]:
    changed_from_event = await _python_files_changed_since(root, base)
    changed_after_activation = await _python_files_changed_since(root, activation)
    return tuple(sorted(changed_from_event.intersection(changed_after_activation)))


def _event_json(path: Path) -> dict[str, JsonValue]:
    value = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        message = "GitHub event payload must be a JSON object"
        raise TypeError(message)
    return value


def _comparison_base(arguments: argparse.Namespace, activation_commit: str) -> str:
    base = cast("str", arguments.base)
    if base != "github-event":
        return validate_commit_sha(base, "comparison base")
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_name is None or event_path is None:
        message = "GITHUB_EVENT_NAME and GITHUB_EVENT_PATH are required for --base github-event"
        raise RuntimeError(message)
    return comparison_base(event_name, _event_json(Path(event_path)), activation_commit)


async def _snapshot(arguments: argparse.Namespace) -> int:
    root = cast("Path", arguments.root).resolve(strict=True)
    status = await _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        message = "immutable snapshots require a clean source worktree"
        raise RuntimeError(message)
    profile_name = cast("str", arguments.profile)
    profile = current_profile(root) if profile_name == "current" else historical_profile(root)
    payload = await collect_snapshot(
        profile,
        role=cast("str", arguments.role),
        evidence_url=cast("str | None", arguments.evidence_url),
    )
    expected_commit = cast("str", arguments.expect_commit)
    expected_tree = cast("str", arguments.expect_tree)
    if payload.get("source_commit") != expected_commit:
        message = "snapshot source commit does not match --expect-commit"
        raise ValueError(message)
    if payload.get("source_tree") != expected_tree:
        message = "snapshot source tree does not match --expect-tree"
        raise ValueError(message)
    output = cast("Path", arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(payload), encoding="utf-8")
    sys.stdout.write(f"wrote {output} for {expected_commit}\n")
    return 0


async def _verify(arguments: argparse.Namespace) -> int:
    root = Path.cwd().resolve(strict=True)
    baseline_path = cast("Path", arguments.baseline).resolve(strict=True)
    baseline = _json_object(baseline_path)
    activation_commit = baseline.get("source_commit")
    if not isinstance(activation_commit, str):
        message = "activation source_commit must be text"
        raise TypeError(message)
    if not await _is_ancestor(root, activation_commit):
        message = "activation source commit is not an ancestor of the candidate"
        raise RuntimeError(message)
    candidate = await collect_snapshot(current_profile(root), role="candidate", evidence_url=None)
    if candidate.get("tool_versions") != baseline.get("tool_versions"):
        message = "candidate locked tool versions differ from the activation baseline"
        raise RuntimeError(message)
    changed = await _changed_python_files(
        root,
        _comparison_base(arguments, activation_commit),
        activation_commit,
    )
    failures = verify_snapshots(baseline, candidate, changed)
    report_path = cast("Path | None", arguments.candidate_report)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(canonical_json(candidate), encoding="utf-8")
    if failures:
        sys.stderr.write("Quality ratchet failed:\n")
        for failure in failures:
            sys.stderr.write(f"- {failure}\n")
        return 1
    sys.stdout.write(f"Quality ratchet passed; {len(changed)} changed Python file(s) are clean.\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested ratchet operation and return its enforcement status.

    Returns:
        Zero on success, or one when the candidate violates the ratchet.

    Raises:
        ValueError: If the parsed command has no implementation.
    """
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    command = cast("str", arguments.command)
    if command == "snapshot":
        return anyio.run(_snapshot, arguments)
    if command == "verify":
        return anyio.run(_verify, arguments)
    message = f"unsupported ratchet command: {command}"
    raise ValueError(message)


if __name__ == "__main__":
    raise SystemExit(main())
