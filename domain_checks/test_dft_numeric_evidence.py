# Copyright (c) 2026 PitchAI. All rights reserved.
"""Unrepresentable numeric evidence remains a sanitized fault, never recovery."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .dft_access_segments import read_production_window
from .dft_cutover_config import parse_cutover_boundary
from .dft_cycle import DftCycle, DftCycleConfig
from .dft_retention_consumer import checker_observation
from .dft_test_support import require, require_error
from .test_dft_cutover import shared_line

if TYPE_CHECKING:
    from .config_values import ConfigValue

_UNREPRESENTABLE = 10**400
_LARGE_FINITE_AGE = 1e308
_NOW = datetime(2026, 10, 2, 12, 10, tzinfo=UTC)


def _response(age: float) -> str:
    return json.dumps({"age_seconds": age, "overdue_segments": 3, "errors": []})


class TestNumericEvidence(unittest.IsolatedAsyncioTestCase):
    """Use synthetic JSON, local child processes and private temporary journals."""

    @staticmethod
    def test_checker_age_cannot_overflow_into_cycle_failure() -> None:
        """Invalid large values and non-finite ages produce fixed failure codes."""
        for age in (_UNREPRESENTABLE, -_UNREPRESENTABLE, float("inf"), float("nan"), True):
            result = checker_observation(0, _response(age).encode())
            require(condition=not result.healthy and result.age_seconds is None
                    and result.errors == ("checker_age_unavailable",),
                    message="invalid numeric age escaped failure classification")
        stale = checker_observation(0, _response(_LARGE_FINITE_AGE).encode())
        require(condition=stale.age_seconds is not None and math.isclose(stale.age_seconds, _LARGE_FINITE_AGE)
                and stale.errors == ("heartbeat_stale",),
                message="representable stale evidence was changed")

    @staticmethod
    def test_segment_epoch_cannot_escape_coverage_fault() -> None:
        """Malformed original epochs never become counters or raw durable data."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for epoch in (_UNREPRESENTABLE, -_UNREPRESENTABLE, float("inf"), float("nan")):
                row = {"class": "dft-web-access-v1", "capture_hour": "2026-10-02T12+00:00",
                       "event_unix": epoch, "status": 200, "agent": "private-synthetic"}
                (root / "dft-access-2026-10-02T12+00:00.jsonl").write_text(json.dumps(row) + "\n")
                with require_error(ValueError, "invalid_segment_record"):
                    read_production_window(root, now=_NOW, window_seconds=300)

    @staticmethod
    def test_cutover_epoch_cannot_escape_allocation_refusal() -> None:
        """Either unrepresentable original admission time is rejected explicitly."""
        for key in ("writer_adopted_at", "old_workers_drained_at"):
            value: dict[str, ConfigValue] = {"writer_adopted_at": 1, "old_workers_drained_at": 1}
            value[key] = _UNREPRESENTABLE
            with require_error(ValueError, "dft_invalid_cutover_boundary"):
                parse_cutover_boundary(value)

    @staticmethod
    async def test_actual_checker_fault_survives_restart_and_acknowledgement() -> None:
        """A local malformed response is persisted until fresh acknowledged health.

        Raises:
            AssertionError: The enabled isolated consumer fails to allocate its journal.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "__init__.py").write_text("")
            checker = scripts / "dft_access_log_status.py"
            checker.write_text(f"print({_response(_UNREPRESENTABLE)!r})\n")
            shared = root / "shared"
            shared.write_text(shared_line("other.pitchai.net", _NOW, 200))
            config = DftCycleConfig("shared", root, root / "config", root / "consumer.sqlite")
            cycle = DftCycle(config)
            if cycle.journal is None:
                message = "isolated consumer has no journal"
                raise AssertionError(message)
            _ = cycle.read_access(access_log_path=str(shared), now=_NOW, window_seconds=300, max_bytes=1000)
            with patch("domain_checks.dft_checker_process.os.geteuid", return_value=0):
                await cycle.observe(now=1)
            incident_id = cycle.summary.get("incident_id")
            original = cycle.journal.pending(now=1)
            require(condition=original is not None and "checker_age_unavailable" in original.payload
                    and str(_UNREPRESENTABLE) not in original.payload,
                    message="malformed checker response did not create sanitized durable intent")
            cycle.close()
            cycle = DftCycle(replace(config, acknowledged_incident_id=str(incident_id)))
            _ = cycle.read_access(access_log_path=str(shared), now=_NOW, window_seconds=300, max_bytes=1000)
            with patch("domain_checks.dft_checker_process.os.geteuid", return_value=0):
                await cycle.observe(now=2)
            require(condition=cycle.summary.get("incident_id") == incident_id
                    and cycle.summary.get("incident_closed_at") is None,
                    message="malformed response closed or replaced the acknowledged incident")
            checker.write_text(f"print({_response(1)!r})\n")
            _ = cycle.read_access(access_log_path=str(shared), now=_NOW, window_seconds=300, max_bytes=1000)
            with patch("domain_checks.dft_checker_process.os.geteuid", return_value=0):
                await cycle.observe(now=3)
            recovered_at = 3
            require(condition=cycle.summary.get("incident_id") == incident_id
                    and cycle.summary.get("incident_closed_at") == recovered_at,
                    message="fresh healthy evidence did not recover the same acknowledged incident")
            if cycle.journal is not None:
                require(condition=cycle.journal.pending(now=3) == original,
                        message="new recovery overtook the original unaccepted failure")
            cycle.close()
