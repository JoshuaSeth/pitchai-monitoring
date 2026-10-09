# Copyright (c) 2026 PitchAI. All rights reserved.
"""Verify standalone HOME ownership and existing CLI failure boundaries."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest

from domain_checks.dft_test_support import require

from . import playwright_python
from .python_home import invocation_home


class PythonHomeTests(unittest.TestCase):
    """Use synthetic CLI work, without a browser or child process."""

    @staticmethod
    def test_configured_home_is_unchanged_including_empty() -> None:
        """Setdefault previously preserved an empty existing HOME as well."""
        for configured in ("", "/synthetic/preexisting-home"):
            with patch.dict(os.environ, {"HOME": configured}):
                with invocation_home():
                    require(condition=os.environ["HOME"] == configured, message="existing HOME changed")
                require(condition=os.environ["HOME"] == configured, message="existing HOME removed")

    @staticmethod
    def test_missing_home_is_private_and_removed_after_failure() -> None:
        """Temporary state survives the invocation and is cleaned on ordinary error."""
        allocated: list[Path] = []

        def failing_operation() -> None:
            with invocation_home():
                home = Path(os.environ["HOME"])
                allocated.append(home)
                require(condition=home.stat().st_mode & 0o077 == 0, message="HOME permits another principal")
                _ = (home / "test-cache").write_text("synthetic", encoding="utf-8")
                _ = int("synthetic failure")

        with patch.dict(os.environ):
            os.environ.pop("HOME", None)
            with pytest.raises(ValueError, match="synthetic failure"):
                failing_operation()
            require(condition="HOME" not in os.environ, message="owned environment entry survived")
            require(condition=len(allocated) == 1 and not allocated[0].exists(), message="owned HOME survived")

    @staticmethod
    def test_real_cli_runners_keep_exit_and_cancellation_boundaries() -> None:
        """Exercise AnyIO's asyncio runner with local substituted CLI work."""
        allocated: list[Path] = []

        async def fake_main(_arguments: list[str]) -> int:
            await asyncio.sleep(0)
            allocated.append(Path(os.environ["HOME"]))
            return 0

        async def cancelled_main(_arguments: list[str]) -> int:
            await asyncio.sleep(0)
            allocated.append(Path(os.environ["HOME"]))
            raise asyncio.CancelledError

        with patch.dict(os.environ), patch.object(sys, "argv", ["synthetic"]):
            os.environ.pop("HOME", None)
            with patch.object(playwright_python, "_amain", fake_main), pytest.raises(SystemExit) as exit_result:
                playwright_python.main()
            require(condition=exit_result.value.code == 0, message="normal exit changed")
            with patch.object(playwright_python, "_amain", cancelled_main), pytest.raises(asyncio.CancelledError):
                playwright_python.main()
            require(condition="HOME" not in os.environ, message="cancellation retained environment entry")
        remaining = [home for home in allocated if home.exists()]
        expected_runs = 2
        require(condition=len(allocated) == expected_runs and not remaining, message="owned CLI home survived")

    @staticmethod
    def test_keyboard_interrupt_retains_exit_130() -> None:
        """The existing outer interrupt boundary remains active with private HOME."""
        with patch.dict(os.environ), patch.object(anyio, "run", side_effect=KeyboardInterrupt):
            os.environ.pop("HOME", None)
            with pytest.raises(SystemExit) as exit_result:
                playwright_python.main()
            expected_exit = 130
            require(condition=exit_result.value.code == expected_exit, message="interrupt exit changed")
            require(condition="HOME" not in os.environ, message="interrupt retained owned environment entry")
