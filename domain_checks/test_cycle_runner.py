# Copyright (c) 2026 PitchAI. All rights reserved.
"""Repeat timing, error precedence and cleanup at the native loop boundary."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .cycle_iteration import CycleIteration
from .cycle_runner import CycleRunner
from .cycle_startup import CycleLimits
from .dft_cycle import DftCycle
from .dft_test_support import require
from .test_cycle_iteration import fixture as iteration_fixture

if TYPE_CHECKING:
    from .browser_admission import BrowserConnection


def fixture() -> tuple[CycleRunner[BrowserConnection], AsyncMock, AsyncMock]:
    """Return a real runner with a synthetic browser and unopened DFT input."""
    iteration, _calls, _observation = iteration_fixture()
    close = AsyncMock()
    ensure = AsyncMock()
    browser = MagicMock(close=close)
    admission = MagicMock(ensure=ensure, browser=browser)
    cast("MagicMock", iteration.phases.domains).browser = admission
    return CycleRunner(iteration, CycleLimits.read({})), ensure, close


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    """All cycle/host/transport effects are replaced by explicit local observations."""

    @staticmethod
    async def test_once_skips_meta_and_closes_dft_before_browser() -> None:
        """The once return keeps its pre-meta boundary and original cleanup order."""
        runner, ensure, close = fixture()
        order = MagicMock()
        order.attach_mock(close, "browser_close")
        with (patch.object(CycleIteration, "run", new=AsyncMock()) as iteration,
              patch.object(DftCycle, "close") as dft):
            order.attach_mock(dft, "dft_close")
            result = await runner.run(once=True)
        require(condition=result == 0, message="once exit changed")
        ensure.assert_awaited_once()
        iteration.assert_awaited_once()
        cast("MagicMock", runner.iteration.phases.meta.run).assert_not_called()
        names = [cast("str", call[0]) for call in order.mock_calls]
        require(condition=names == ["dft_close", "browser_close"], message="cleanup reordered")

    @staticmethod
    async def test_initial_admission_failure_stays_outside_cleanup() -> None:
        """The extraction does not invent ownership before the old try/finally begins."""
        runner, ensure, close = fixture()
        ensure.side_effect = RuntimeError("admission")
        with (patch.object(CycleIteration, "run", new=AsyncMock()) as iteration,
              patch.object(DftCycle, "close") as dft):
            result = await asyncio.gather(runner.run(once=True), return_exceptions=True)
        require(condition=isinstance(result[0], RuntimeError), message="admission failure suppressed")
        iteration.assert_not_awaited()
        dft.assert_not_called()
        close.assert_not_awaited()

    @staticmethod
    async def test_cancelled_cycle_closes_resources_and_propagates() -> None:
        """Cancellation after admission reaches the caller after existing cleanup."""
        runner, _ensure, close = fixture()
        with (patch.object(CycleIteration, "run", new=AsyncMock(side_effect=asyncio.CancelledError)),
              patch.object(DftCycle, "close") as dft):
            result = await asyncio.gather(runner.run(once=True), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="cycle cancellation suppressed")
        dft.assert_called_once()
        close.assert_awaited_once()

    @staticmethod
    async def test_failed_dft_close_preserves_exception_precedence() -> None:
        """A DFT close failure still prevents the later browser close."""
        runner, _ensure, close = fixture()
        with (patch.object(CycleIteration, "run", new=AsyncMock()),
              patch.object(DftCycle, "close", side_effect=RuntimeError("dft close"))):
            result = await asyncio.gather(runner.run(once=True), return_exceptions=True)
        require(condition=isinstance(result[0], RuntimeError), message="DFT close failure suppressed")
        close.assert_not_awaited()

    @staticmethod
    async def test_repeat_samples_elapsed_before_meta_and_sleeps_after_persistence() -> None:
        """Meta and post-meta writes keep the same timing before cancellation in sleep."""
        runner, _ensure, close = fixture()
        phases = cast("MagicMock", runner.iteration.phases.meta)
        meta_run = AsyncMock()
        phases.run = meta_run
        order = MagicMock()
        order.attach_mock(meta_run, "meta")
        with (patch.object(CycleIteration, "run", new=AsyncMock()),
              patch.object(DftCycle, "close"),
              patch("domain_checks.cycle_runner.time.time", side_effect=[100.0, 101.0, 108.0]),
              patch("domain_checks.cycle_persistence.CyclePersistence.flush", new=AsyncMock()) as flush,
              patch("domain_checks.cycle_persistence.CyclePersistence.persist") as persist,
              patch("domain_checks.cycle_runner.asyncio.sleep",
                    new=AsyncMock(side_effect=asyncio.CancelledError)) as sleep):
            order.attach_mock(flush, "flush")
            order.attach_mock(persist, "persist")
            order.attach_mock(sleep, "sleep")
            result = await asyncio.gather(runner.run(once=False), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="sleep cancellation suppressed")
        sleep.assert_awaited_once_with(max(0.0, runner.limits.interval - 7.0))
        persist.assert_called_once_with("post_meta")
        names = [cast("str", call[0]) for call in order.mock_calls]
        require(condition=names == ["meta", "flush", "persist", "sleep"], message="post-cycle order changed")
        close.assert_awaited_once()
