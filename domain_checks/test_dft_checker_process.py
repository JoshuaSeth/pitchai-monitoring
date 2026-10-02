# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exercise bounded subprocess capture using temporary synthetic checker code."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .dft_checker_process import observe_checker
from .dft_test_support import require


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
