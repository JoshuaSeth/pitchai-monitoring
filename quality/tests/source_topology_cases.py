# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed source-topology cases shared by the ratchet unit suite."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from pitchai_quality.ratchet_commands import current_profile
from pitchai_quality.source_files import iter_python_files, validate_tracked_source_topology

_GIT_ENV_PREFIX = "GIT_"


def _git(root: Path, *arguments: str) -> None:
    environment_names = (name for name in os.environ if not name.startswith(_GIT_ENV_PREFIX))
    environment = {name: os.environ[name] for name in environment_names}
    command = ("git", "-C", str(root), *arguments)
    pid = os.posix_spawnp(command[0], command, environment)
    _completed_pid, status = os.waitpid(pid, 0)
    return_code = os.waitstatus_to_exitcode(status)
    if return_code != 0:
        message = f"Git test setup failed with status {return_code}: {' '.join(command)}"
        raise RuntimeError(message)


def _tracked(root: Path, *paths: str) -> None:
    _git(root, "init", "-q")
    _git(root, "add", "--", *paths)


def test_excluded_tracked_python_and_package_symlink_fail_closed() -> None:
    """Reject the exact move-under-build plus package-symlink bypass.

    Raises:
        AssertionError: If either discovery path omits a topology violation.

    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        hidden_package = root / "build" / "runtime_pkg"
        hidden_package.mkdir(parents=True)
        (hidden_package / "__init__.py").write_text("VALUE = 7\n", encoding="utf-8")
        (root / "build" / "direct_hidden.py").write_text("HIDDEN = 1\n", encoding="utf-8")
        (root / "runtime_pkg").symlink_to(Path("build") / "runtime_pkg", target_is_directory=True)
        _tracked(root, "build", "runtime_pkg")

        with pytest.raises(RuntimeError) as checker_failure:
            iter_python_files((root,), repository_root=root)
        with pytest.raises(RuntimeError) as ratchet_failure:
            current_profile(root)
        failures = (str(checker_failure.value), str(ratchet_failure.value))
        expected_fragments = (
            "tracked Python source is hidden by an excluded directory: build/direct_hidden.py",
            "tracked Python source is hidden by an excluded directory: build/runtime_pkg/__init__.py",
            "tracked symlink is forbidden in source topology: runtime_pkg",
        )
        for failure in failures:
            for expected in expected_fragments:
                if expected not in failure:
                    message = f"missing source-topology violation: {expected}"
                    raise AssertionError(message)


def test_internal_source_symlink_fails_closed() -> None:
    """Reject a tracked Python alias even when its target stays inside the repo."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "target.py").write_text("VALUE = 11\n", encoding="utf-8")
        (root / "alias.py").symlink_to("target.py")
        _tracked(root, "target.py", "alias.py")

        expected = "tracked symlink is forbidden in source topology: alias.py"
        with pytest.raises(RuntimeError, match=expected):
            iter_python_files((root,), repository_root=root)
        with pytest.raises(RuntimeError, match=expected):
            current_profile(root)


def test_untracked_generated_python_remains_excluded() -> None:
    """Keep generated caches outside the gate when Git does not track them.

    Raises:
        AssertionError: If either discovery path includes generated Python.

    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.py"
        source.write_text("VALUE = 17\n", encoding="utf-8")
        generated = root / "build" / "generated.py"
        generated.parent.mkdir()
        generated.write_text("GENERATED = True\n", encoding="utf-8")
        _tracked(root, "source.py")

        validate_tracked_source_topology(root)
        expected = (source.resolve(),)
        if iter_python_files((root,), repository_root=root) != expected:
            message = "complete-source discovery changed the generated-cache exclusion"
            raise AssertionError(message)
        if current_profile(root).python_files != expected:
            message = "ratchet discovery changed the generated-cache exclusion"
            raise AssertionError(message)


SOURCE_TOPOLOGY_TESTS = (
    test_excluded_tracked_python_and_package_symlink_fail_closed,
    test_internal_source_symlink_fails_closed,
    test_untracked_generated_python_remains_excluded,
)
