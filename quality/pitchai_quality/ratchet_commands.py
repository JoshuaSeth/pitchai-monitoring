# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build and execute exact commands for quality debt snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio

from pitchai_quality.strict_policy import (
    EXPECTED_GATES,
    EXPECTED_NON_SOURCE_DIRECTORIES,
    RUFF_ARGUMENTS,
    SEMGREP_ARGUMENTS,
)
from pitchai_quality.tool_environment import locked_tool_environment

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_CUSTOM_GATES = (
    "nested-event-loops",
    "no-vague-signatures",
    "no-single-use-one-line-functions",
    "no-pure-wrapper-functions",
    "no-dense-inline-comprehensions",
)
_LEGACY_GATES = (*_CUSTOM_GATES, "ruff", "basedpyright", "pylint", "semgrep")
_LEGACY_ROOTS = ("domain_checks", "e2e_registry", "e2e_runner", "e2e_sandbox")


@dataclass(frozen=True)
class QualityProfile:
    """One exact source/toolchain layout supported by the snapshotter."""

    root: Path
    gates: tuple[str, ...]
    python_files: tuple[Path, ...]
    runtime_files: tuple[Path, ...]
    venv: Path
    config_root: Path
    custom_package: bool


@dataclass(frozen=True)
class GateRun:
    """Captured output and command for one quality gate."""

    name: str
    command: tuple[str, ...]
    return_code: int
    stdout: bytes
    stderr: bytes


def _is_source(root: Path, path: Path, suffixes: frozenset[str]) -> bool:
    relative = path.relative_to(root)
    return (
        path.is_file() and path.suffix in suffixes and not EXPECTED_NON_SOURCE_DIRECTORIES.intersection(relative.parts)
    )


def _discover(root: Path, roots: Sequence[Path], suffixes: frozenset[str]) -> tuple[Path, ...]:
    files: list[Path] = []
    for source_root in roots:
        candidates = source_root.rglob("*") if source_root.is_dir() else (source_root,)
        for path in candidates:
            if not _is_source(root, path, suffixes):
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                message = f"Python source symlink escapes repository root: {path}"
                raise ValueError(message)
            files.append(resolved)
    return tuple(dict.fromkeys(sorted(files)))


def current_profile(root: Path) -> QualityProfile:
    """Return the current complete-source strict profile."""
    resolved = root.resolve(strict=True)
    python_files = _discover(resolved, (resolved,), frozenset({".py", ".pyi"}))
    runtime_files = tuple(path for path in python_files if path.suffix == ".py")
    return QualityProfile(
        root=resolved,
        gates=EXPECTED_GATES,
        python_files=python_files,
        runtime_files=runtime_files,
        venv=resolved / "quality" / ".venv",
        config_root=resolved / "quality",
        custom_package=True,
    )


def historical_profile(root: Path) -> QualityProfile:
    """Return the exact nine-gate layout used at the July baseline."""
    resolved = root.resolve(strict=True)
    source_roots = tuple(resolved / name for name in _LEGACY_ROOTS)
    python_files = _discover(resolved, source_roots, frozenset({".py", ".pyi"}))
    runtime_files = tuple(path for path in python_files if path.suffix == ".py")
    return QualityProfile(
        root=resolved,
        gates=_LEGACY_GATES,
        python_files=python_files,
        runtime_files=runtime_files,
        venv=resolved / ".venv",
        config_root=resolved,
        custom_package=False,
    )


def _executable(profile: QualityProfile, name: str) -> str:
    path = profile.venv / "bin" / name
    if not path.is_file():
        message = f"locked executable is missing: {path}"
        raise FileNotFoundError(message)
    return str(path)


def _custom_command(profile: QualityProfile, gate: str) -> tuple[str, ...]:
    python = _executable(profile, "python")
    if gate == "no-validation-bypasses":
        return (python, "-m", "pitchai_quality.check_no_validation_bypasses")
    module = gate.replace("-", "_")
    if profile.custom_package:
        return (python, "-m", f"pitchai_quality.check_{module}", *(str(path) for path in profile.python_files))
    script = profile.root / "scripts" / f"check_{module}.py"
    return (python, str(script), *(str(path) for path in profile.python_files))


def _ruff_command(profile: QualityProfile) -> tuple[str, ...]:
    if profile.custom_package:
        arguments = (*RUFF_ARGUMENTS, "--output-format=json")
    else:
        arguments = (
            "check",
            "--no-cache",
            "--config",
            str(profile.config_root / "pyproject.toml"),
            "--output-format=json",
        )
    return (_executable(profile, "ruff"), *arguments, *(str(path) for path in profile.runtime_files))


def _basedpyright_command(profile: QualityProfile) -> tuple[str, ...]:
    config = profile.config_root / "pyproject.toml"
    return (
        _executable(profile, "basedpyright"),
        "--project",
        str(config),
        "--warnings",
        "--outputjson",
        *(str(path) for path in profile.python_files),
    )


def _pylint_command(profile: QualityProfile) -> tuple[str, ...]:
    config = profile.config_root / "pyproject.toml"
    return (
        _executable(profile, "pylint"),
        "--rcfile",
        str(config),
        "--jobs=1",
        "--fail-under=10",
        "--output-format=json2",
        *(str(path) for path in profile.runtime_files),
    )


def _semgrep_command(profile: QualityProfile) -> tuple[str, ...]:
    config = profile.config_root / ".semgrep.yml"
    arguments = SEMGREP_ARGUMENTS if profile.custom_package else ("--error", "--metrics=off")
    return (
        _executable(profile, "semgrep"),
        "scan",
        "--config",
        str(config),
        *arguments,
        "--json",
        *(str(path) for path in profile.runtime_files),
    )


def command_for(profile: QualityProfile, gate: str) -> tuple[str, ...]:
    """Return one exact machine-output command without changing policy semantics.

    Returns:
        The complete subprocess command.

    Raises:
        ValueError: If the gate has no registered command.
    """
    if gate in {*_CUSTOM_GATES, "no-validation-bypasses"}:
        return _custom_command(profile, gate)
    if gate == "ruff":
        return _ruff_command(profile)
    if gate == "basedpyright":
        return _basedpyright_command(profile)
    if gate == "pylint":
        return _pylint_command(profile)
    if gate == "semgrep":
        return _semgrep_command(profile)
    message = f"unsupported quality gate: {gate}"
    raise ValueError(message)


async def run_gate(profile: QualityProfile, gate: str) -> GateRun:
    """Execute one gate and retain complete output for strict parsing.

    Returns:
        The command, status, and complete process output.
    """
    command = command_for(profile, gate)
    completed = await anyio.run_process(
        command,
        cwd=profile.root,
        env=locked_tool_environment(profile.venv),
        check=False,
    )
    return GateRun(gate, command, completed.returncode, completed.stdout, completed.stderr)


async def tool_versions(profile: QualityProfile) -> dict[str, str]:
    """Read exact locked executable versions from the selected environment.

    Returns:
        Version output keyed by locked executable name.

    Raises:
        RuntimeError: If a tool emits no version text.
    """
    versions: dict[str, str] = {}
    for tool in ("python", "ruff", "basedpyright", "pylint", "semgrep"):
        completed = await anyio.run_process(
            (_executable(profile, tool), "--version"),
            env=locked_tool_environment(profile.venv),
            check=True,
        )
        output = b"\n".join((completed.stdout, completed.stderr)).decode().strip()
        version_line = next((line for line in output.splitlines() if line), "")
        if not version_line:
            message = f"{tool} --version emitted no version text"
            raise RuntimeError(message)
        versions[tool] = version_line
    return versions
