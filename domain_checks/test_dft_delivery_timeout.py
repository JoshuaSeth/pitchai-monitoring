# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded receiver waits with durable uncertainty, using no network."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .dft_cycle import DftCycle, DftCycleConfig
from .dft_retention_consumer import CheckerObservation
from .dft_test_support import require

if TYPE_CHECKING:
    from .dft_journal import PendingTransition


@dataclass
class WaitingReceiver:
    """Capture synthetic bytes and await an isolated in-memory signal."""

    calls: list[PendingTransition] = field(default_factory=list)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False

    async def __call__(self, pending: PendingTransition) -> str:
        """Wait for the test signal, preserving evidence of deadline cancellation.

        Returns:
            An isolated receipt only when the test explicitly releases this call.
        """
        self.calls.append(pending)
        try:
            await self.ready.wait()
        finally:
            self.cancelled = not self.ready.is_set()
        return "isolated-accepted-receipt"


class TestDeliveryTimeout(unittest.IsolatedAsyncioTestCase):
    """Use temporary consumer state and an in-memory receiver only."""

    @staticmethod
    async def test_deadline_retains_retry_identity_across_restart() -> None:
        """A missing response cannot stall the cycle or imply receipt acceptance."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = DftCycleConfig("shared", root, root / "config", root / "consumer.sqlite")
            receiver = WaitingReceiver()
            cycle = DftCycle(config, receiver)
            require(condition=cycle.journal is not None, message="enabled cycle lacks journal")
            if cycle.journal is None:
                return
            cycle.journal.record(CheckerObservation(errors=("heartbeat_stale",)), now=0)
            original = cycle.journal.pending(now=0)
            with patch("domain_checks.dft_cycle._DELIVERY_TIMEOUT_SECONDS", 0.01):
                await asyncio.wait_for(cycle.deliver_pending(now=0), timeout=1)
            require(condition=receiver.cancelled, message="receiver remained active past cycle deadline")
            require(condition=cycle.journal.pending(now=1) is None,
                    message="uncertain timeout skipped persisted retry backoff")
            cycle.close()
            restored = DftCycle(config, receiver)
            require(condition=restored.journal is not None, message="restart lost journal")
            if restored.journal is None:
                return
            require(condition=restored.journal.pending(now=5) == original,
                    message="timeout lost or replaced the original intent")
            receiver.ready.set()
            await restored.deliver_pending(now=5)
            require(condition=receiver.calls == [original, original],
                    message="deadline retry changed bytes or identity")
            require(condition=restored.journal.pending(now=5) is None,
                    message="explicit isolated receipt did not settle intent")
            restored.close()
