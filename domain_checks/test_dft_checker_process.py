# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exercise bounded subprocess capture using temporary synthetic checker code."""

from __future__ import annotations

import asyncio
import os
import signal
import tempfile
import unittest
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .dft_checker_process import observe_checker
from .dft_test_support import require

if TYPE_CHECKING:
    from .dft_retention_consumer import CheckerObservation


class TestCheckerProcess(unittest.IsolatedAsyncioTestCase):
    """Never call the real producer checker or any network endpoint."""

    @staticmethod
    async def test_local_synthetic_checker_responses() -> None:
        """Zero, nonzero and oversized child outputs stay bounded and classified."""
        cases = [
            ('print(\'{"age_seconds":1,"overdue_segments":3,"errors":[]}\')', True),
            ('print(\'{"age_seconds":1,"overdue_segments":0,"errors":[]}\'); raise SystemExit(1)', False),
            ('print("X" * 1000000)', False),
            ("import time; time.sleep(60)", False),
        ]
        for source, expected_health in cases:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scripts = root / "scripts"
                scripts.mkdir()
                (scripts / "__init__.py").write_text("", encoding="utf-8")
                (scripts / "dft_access_log_status.py").write_text(source, encoding="utf-8")
                with patch("domain_checks.dft_checker_process.os.geteuid", return_value=0):
                    observed = await observe_checker(root, root / "synthetic-config.json")
                require(condition=observed.healthy == expected_health,
                        message="synthetic process response was classified incorrectly")

    @staticmethod
    async def test_missing_source_is_a_failed_observation() -> None:
        """An unavailable allocated source cannot manufacture healthy status."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("domain_checks.dft_checker_process.os.geteuid", return_value=0):
                observed = await observe_checker(root / "missing", root / "config.json")
            require(condition=not observed.healthy and observed.errors == ("checker_unavailable",),
                    message="missing checker source did not remain a failure")

    @staticmethod
    async def test_descendant_stdout_cannot_extend_deadline() -> None:
        """An exited checker with an inherited open pipe remains a bounded fault."""
        await _check_inherited_pipe('print(\'{"age_seconds":1,"overdue_segments":0,"errors":[]}\')')

    @staticmethod
    async def test_oversized_response_cleanup_is_bounded() -> None:
        """Refusing oversized output must also terminate its inherited pipe owner."""
        await _check_inherited_pipe('print("X" * 1000000)')


async def _check_inherited_pipe(response: str) -> None:
    with tempfile.TemporaryDirectory() as directory, \
            patch("domain_checks.dft_checker_process.os.geteuid", return_value=0), \
            patch("domain_checks.dft_checker_process._TIMEOUT_SECONDS", 2):
        root = Path(directory)
        scripts = root / "scripts"
        scripts.mkdir()
        (scripts / "__init__.py").write_text("", encoding="utf-8")
        source = (
            "import pathlib, subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "pathlib.Path('child.pid').write_text(str(child.pid))\n" + response + "\n"
        )
        (scripts / "dft_access_log_status.py").write_text(source, encoding="utf-8")
        task = asyncio.create_task(observe_checker(root, root / "synthetic-config.json"))
        try:
            await _require_bounded_failure(task, root / "child.pid")
        finally:
            if not task.done() and (root / "child.pid").is_file():
                with suppress(ProcessLookupError):
                    os.kill(int((root / "child.pid").read_text(encoding="utf-8")), signal.SIGKILL)
            await asyncio.wait_for(task, timeout=2)


async def _require_bounded_failure(task: asyncio.Task[CheckerObservation], child_pid: Path) -> None:
    await asyncio.wait({task}, timeout=5)
    child_started = await asyncio.to_thread(child_pid.is_file)
    require(condition=child_started, message="isolated descendant was not started")
    require(condition=task.done(), message="inherited stdout escaped the checker deadline")
    observed = await task
    require(condition=not observed.healthy, message="incomplete inherited response became healthy")
