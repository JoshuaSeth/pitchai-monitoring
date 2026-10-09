# Copyright (c) 2026 PitchAI. All rights reserved.
"""Durable retry/uncertainty proof in disposable SQLite files only."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .dft_journal import DftJournal
from .dft_retention_consumer import CheckerObservation
from .dft_test_support import require


class TestDftJournal(unittest.TestCase):
    """No real transition or recipient is used to exercise delivery state."""

    @staticmethod
    def test_uncertain_failure_survives_restart_and_precedes_recovery() -> None:
        """Retry retains original bytes and identity, then allows one recovery."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "consumer.db"
            first = DftJournal(path)
            incident = first.record(CheckerObservation(errors=("retention_fault_latched",)), now=1)
            original = first.pending(now=1)
            require(condition=original is not None and incident is not None, message="failure intent was not committed")
            if original is None or incident is None:
                return
            first.settle(original.delivery_id, receiver_id=None, now=1)
            first.close()
            restored = DftJournal(path)
            require(condition=restored.current() == incident, message="process restart lost incident identity")
            require(condition=restored.pending(now=2) is None, message="retry ignored persisted backoff")
            restored.record(CheckerObservation(errors=("checker_unavailable",)), now=2)
            restored.record(CheckerObservation(age_seconds=1), now=3)
            require(condition=restored.current() == incident,
                    message="warning or unacknowledged health closed incident")
            restored.record(CheckerObservation(age_seconds=1, overdue_segments=8), now=4,
                            acknowledged_incident_id=incident.incident_id)
            require(condition=restored.pending(now=6) == original, message="recovery overtook uncertain failure")
            restored.settle(original.delivery_id, receiver_id="isolated-failure-receipt", now=6)
            recovery = restored.pending(now=6)
            require(condition=recovery is not None and recovery.delivery_id.endswith(":recovered"),
                    message="accepted failure did not release queued recovery")
            if recovery is not None:
                restored.settle(recovery.delivery_id, receiver_id=None, now=6)
                restored.close()
                restored = DftJournal(path)
                require(condition=restored.pending(now=11) == recovery, message="recovery retry changed original bytes")
                restored.settle(recovery.delivery_id, receiver_id="isolated-recovery-receipt", now=11)
            require(condition=restored.pending(now=99) is None, message="accepted receipt did not settle intent")
            restored.close()
