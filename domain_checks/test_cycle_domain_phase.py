# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic selection, completion ordering and cancellation at the cycle boundary."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .browser_admission import BrowserAdmission
from .common_check import DomainCheckResult, DomainCheckSpec
from .cycle_domain_phase import CycleDomainPhase, CycleInventory
from .dft_test_support import require
from .domain_entries import DomainEntryConfig
from .domain_polling import DomainPolling
from .domain_result_phase import DomainResultPhase
from .test_cycle_persistence import fixture as persistence_fixture

if TYPE_CHECKING:
    from .browser_admission import BrowserConnection
    from .cycle_persistence import CyclePersistence


def fixture(
    poll: AsyncMock, observe: AsyncMock,
) -> tuple[CycleDomainPhase[BrowserConnection], CyclePersistence, AsyncMock]:
    """Return a native cycle phase with local-only admission and polling effects."""
    state = persistence_fixture()
    entries = [DomainEntryConfig("first.invalid", "first.invalid"),
               DomainEntryConfig("second.invalid", "second.invalid"),
               DomainEntryConfig("stopped.invalid", "stopped.invalid", disabled=True)]
    specs = {entry.domain: DomainCheckSpec(entry.domain, "https://fixture.invalid") for entry in entries}
    ensure = AsyncMock(return_value=None)
    browser = cast("BrowserAdmission[BrowserConnection]", MagicMock(spec=BrowserAdmission, ensure=ensure))
    polling = cast("DomainPolling[BrowserConnection]", MagicMock(spec=DomainPolling, run=poll))
    result_phase = cast("DomainResultPhase", MagicMock(spec=DomainResultPhase, observe=observe))
    phase = CycleDomainPhase(CycleInventory(entries, specs, None), state, browser, polling, result_phase, 60)
    return phase, state, ensure


class DomainCycleTests(unittest.IsolatedAsyncioTestCase):
    """Real asyncio tasks preserve completion order without network or browser access."""

    @staticmethod
    async def test_selection_clears_only_stopped_state_and_keeps_completion_order() -> None:
        """Stopped aliases clear before polling; results are consumed as completed."""
        release = asyncio.Event()
        polled: list[str] = []
        observed: list[str] = []

        async def poll(spec: DomainCheckSpec) -> DomainCheckResult:
            polled.append(spec.domain)
            if spec.domain == "first.invalid":
                await release.wait()
            return DomainCheckResult(spec.domain, ok=True, reason="synthetic", details={"browser_infra_error": True})

        async def observe(result: DomainCheckResult, _stamp: float) -> None:
            observed.append(result.domain)
            if result.domain == "second.invalid":
                release.set()
            await asyncio.sleep(0)

        phase, state, ensure = fixture(AsyncMock(side_effect=poll), AsyncMock(side_effect=observe))
        state.records.domains.last_ok.update({"stopped.invalid": False, "unrelated.invalid": False})
        state.records.history["stopped.invalid"] = []
        state.health.dns_ips["stopped.invalid"] = ["192.0.2.1"]
        for probe in state.health.probes.values():
            probe.last_ok["stopped.invalid"] = False
            probe.last_run_ts["stopped.invalid"] = 50
        with patch("domain_checks.cycle_domain_phase.time.time", return_value=100):
            result = await phase.run(100)
        require(condition=observed == ["second.invalid", "first.invalid"], message="completion order changed")
        require(condition=polled == ["first.invalid", "second.invalid"], message="inventory launch order changed")
        require(condition=result.browser_degraded, message="infrastructure degradation lost")
        require(condition=state.records.domains.last_ok == {"unrelated.invalid": False}, message="unrelated state lost")
        require(condition="stopped.invalid" not in state.records.history and not state.health.dns_ips,
                message="stopped state retained")
        for probe in state.health.probes.values():
            require(condition=not probe.last_ok and not probe.last_run_ts, message="stopped probe state retained")
        require(condition=result.disabled_lines == ["- stopped.invalid: DISABLED"], message="disabled display changed")
        ensure.assert_awaited_once()

    @staticmethod
    async def test_cancelled_observation_retains_sibling_task_ownership() -> None:
        """A cancelled result leaves an already started sibling alive for the owning loop."""
        release = asyncio.Event()
        sibling_tasks: list[asyncio.Task[DomainCheckResult]] = []

        async def poll(spec: DomainCheckSpec) -> DomainCheckResult:
            if spec.domain == "first.invalid":
                await asyncio.sleep(0)
                raise asyncio.CancelledError
            task = asyncio.current_task()
            if task is not None:
                sibling_tasks.append(cast("asyncio.Task[DomainCheckResult]", task))
            await release.wait()
            return DomainCheckResult(spec.domain, ok=True, reason="synthetic", details={})

        observe = AsyncMock()
        phase, state, _ensure = fixture(AsyncMock(side_effect=poll), observe)
        result = await asyncio.gather(phase.run(100), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="cancellation became a result")
        require(condition=len(sibling_tasks) == 1 and not sibling_tasks[0].done(), message="sibling ownership changed")
        require(condition=not state.records.history, message="cancelled cycle recorded complete history")
        observe.assert_not_awaited()
        release.set()
        completed = await asyncio.gather(*sibling_tasks)
        require(condition=completed[0].domain == "second.invalid", message="sibling failed to finish")

    @staticmethod
    async def test_result_failure_does_not_record_complete_history() -> None:
        """A phase error propagates after polling and before history recording."""
        def poll(spec: DomainCheckSpec) -> DomainCheckResult:
            return DomainCheckResult(spec.domain, ok=True, reason="synthetic", details={})

        phase, state, _ensure = fixture(AsyncMock(side_effect=poll),
                                        AsyncMock(side_effect=RuntimeError("synthetic result failure")))
        result = await asyncio.gather(phase.run(100), return_exceptions=True)
        require(condition=isinstance(result[0], RuntimeError), message="result failure suppressed")
        require(condition=not state.records.history, message="failed cycle claimed complete history")
