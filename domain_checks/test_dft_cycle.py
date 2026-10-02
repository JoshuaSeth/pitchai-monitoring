# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated existing-cycle process observations and retry ordering."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .dft_cycle import DftCycle, DftCycleConfig, parse_cycle_config
from .dft_retention_consumer import CheckerObservation
from .dft_test_support import require, require_error
from .test_dft_cutover import shared_line

if TYPE_CHECKING:
    from .dft_journal import PendingTransition


@dataclass
class LocalReceiver:
    """Only store synthetic calls in memory; no transport or socket exists."""

    calls: list[PendingTransition] = field(default_factory=list)
    receipt: str | None = None

    async def __call__(self, pending: PendingTransition) -> str | None:
        """Capture immutable bytes and simulate an uncertain result.

        Returns:
            The configured isolated receipt, or None after simulated uncertainty.

        Raises:
            OSError: The first call simulates a lost response.
        """
        self.calls.append(pending)
        if len(self.calls) == 1:
            message = "isolated lost response"
            raise OSError(message)
        return self.receipt


class TestDftCycle(unittest.IsolatedAsyncioTestCase):
    """No production checker, live event bus or Telegram is invoked."""

    @staticmethod
    async def test_disabled_and_invalid_allocation() -> None:
        """Default runs allocate no state, checker process or receiver."""
        cycle = DftCycle(parse_cycle_config(None))
        await cycle.observe(now=0)
        require(condition=cycle.journal is None and cycle.summary == {"enabled": False},
                message="default configuration unexpectedly enabled DFT")
        with require_error(ValueError, "dft_invalid_allocation_source_root"):
            parse_cycle_config({"enabled": True, "mode": "segments"})

    @staticmethod
    async def test_cycle_restart_warning_and_delivery_retry() -> None:
        """Retain incident through uncertainty and a healthy checker with no coverage.

        Raises:
            AssertionError: An enabled cycle fails to persist its failed observation.
        """
        now = datetime(2026, 10, 2, 12, 10, tzinfo=UTC)
        receiver = LocalReceiver()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared.log"
            shared.write_text(shared_line("other.pitchai.net", now, 200), encoding="utf-8")
            config = DftCycleConfig("shared", root, root / "private.json", root / "consumer.sqlite")
            cycle = DftCycle(config, receiver)
            _ = cycle.read_access(access_log_path=str(shared), now=now, window_seconds=300, max_bytes=1000)
            with patch("domain_checks.dft_cycle.observe_checker",
                       return_value=CheckerObservation(errors=("retention_fault_latched",))):
                await cycle.observe(now=0)
            journal = cycle.journal
            if journal is None:
                message = "enabled cycle did not allocate journal"
                raise AssertionError(message)
            incident = journal.current()
            if incident is None:
                message = "failed checker did not create incident"
                raise AssertionError(message)
            journal.close()
            resumed = DftCycle(config, receiver)
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await resumed.observe(now=5)
            require(condition=receiver.calls[0] == receiver.calls[1], message="retry identity or bytes changed")
            require(condition=resumed.summary.get("incident_id") == incident.incident_id
                    and resumed.summary.get("incident_closed_at") is None,
                    message="missing access coverage claimed a recovery")
            if resumed.journal is not None:
                resumed.journal.close()

    @staticmethod
    async def test_unallocated_route_retains_pending_intent() -> None:
        """Missing receiver creates no outbound attempt or fabricated receipt."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cycle = DftCycle(DftCycleConfig("shared", root, root / "config", root / "consumer.sqlite"))
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await cycle.observe(now=0)
            require(condition=cycle.summary.get("delivery_route_allocated") is False,
                    message="unallocated receiver reported delivery authority")
            if cycle.journal is not None:
                require(condition=cycle.journal.pending(now=0) is not None, message="pending intent disappeared")
                cycle.journal.close()

    @staticmethod
    async def test_recovery_requires_a_new_access_read() -> None:
        """Matching acknowledgement cannot reuse coverage from a failed cycle."""
        now = datetime(2026, 10, 2, 12, 10, tzinfo=UTC)
        recovered_at = 120
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared.log"
            shared.write_text(shared_line("other.pitchai.net", now, 200), encoding="utf-8")
            config = DftCycleConfig("shared", root, root / "config", root / "consumer.sqlite")
            cycle = DftCycle(config)
            _ = cycle.read_access(access_log_path=str(shared), now=now, window_seconds=300, max_bytes=1000)
            with patch("domain_checks.dft_cycle.observe_checker",
                       return_value=CheckerObservation(errors=("retention_fault_latched",))):
                await cycle.observe(now=0)
            incident_id = cycle.summary.get("incident_id")
            cycle.config = replace(config, acknowledged_incident_id=str(incident_id))
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await cycle.observe(now=60)
                require(condition=cycle.summary.get("incident_id") == incident_id
                        and cycle.summary.get("incident_closed_at") is None
                        and cycle.summary.get("errors") == ["access_window_unavailable"],
                        message="stale access coverage closed an acknowledged incident")
                _ = cycle.read_access(access_log_path=str(shared), now=now, window_seconds=300, max_bytes=1000)
                await cycle.observe(now=recovered_at)
            require(condition=cycle.summary.get("incident_id") == incident_id
                    and cycle.summary.get("incident_closed_at") == recovered_at,
                    message="fresh verified coverage did not complete acknowledged recovery")
            cycle.close()
