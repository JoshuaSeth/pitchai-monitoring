# Copyright (c) 2026 PitchAI. All rights reserved.
"""Workflow observation tests with explicitly substituted transport operations."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

from .dft_test_support import require
from .dispatch_client import DispatchConfig
from .dispatch_context import DispatchRequest, DispatchRuntime
from .dispatch_records import DispatchRecords
from .dispatch_workflow import run_dispatch
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .event_bus_delivery import JsonObject


@dataclass
class LocalOperation:
    """Synthetic child work never constructs an HTTP client or sends anything."""

    mode: str
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    cleaned: bool = False
    notices: int = 0

    async def execute(self, _runtime: DispatchRuntime, _request: DispatchRequest) -> None:
        """Substitute only the child operation and expose its cleanup boundary.

        Raises:
            asyncio.CancelledError: The synthetic child cancels its own work.
            TimeoutError: The synthetic dispatch request fails.
        """
        if self.mode == "child":
            message = "synthetic child cancellation"
            raise asyncio.CancelledError(message)
        if self.mode == "parent":
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cleaned = True
        message = "synthetic dispatch timeout"
        raise TimeoutError(message)

    async def notice(self, _client: AsyncClient, _config: TelegramConfig, _text: str) -> tuple[bool, JsonObject]:
        """Return an explicit no-delivery observation without an HTTP operation."""
        self.notices += 1
        return False, {"ok": False, "error": "local fixture; no delivery"}


def _runtime() -> DispatchRuntime:
    client = cast("AsyncClient", MagicMock(name="unused_transport"))
    return DispatchRuntime(
        client, TelegramConfig("synthetic", "synthetic-private"),
        DispatchConfig("https://dispatch.invalid", "synthetic"), {}, DispatchRecords([], {}, []),
    )


async def _cancel_when_entered(task: asyncio.Task[None], entered: asyncio.Event) -> BaseException | None:
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel("synthetic parent cancellation")
    outcomes = await asyncio.gather(task, return_exceptions=True)
    return outcomes[0]


class DispatchWorkflowTests(unittest.IsolatedAsyncioTestCase):
    """Observe cancellation and failure classification at the explicit boundary."""

    @staticmethod
    async def test_child_cancellation_has_no_completion() -> None:
        """A child cancellation must not become a dispatch failure or completion."""
        fixture = LocalOperation("child")
        runtime = _runtime()
        with patch("domain_checks.dispatch_workflow.execute_dispatch", new=fixture.execute):
            result = await asyncio.gather(
                run_dispatch(runtime, DispatchRequest("fixture", "fixture", "Fixture")), return_exceptions=True,
            )
        require(condition=isinstance(result[0], asyncio.CancelledError), message="cancellation did not propagate")
        require(condition=not runtime.records.history and not runtime.records.events, message="cancellation recorded")
        require(condition=not runtime.records.last and fixture.notices == 0, message="cancellation notified")

    @staticmethod
    async def test_parent_cancellation_cleans_child_before_returning() -> None:
        """Parent cancellation must reach the child and finish its cleanup."""
        fixture = LocalOperation("parent")
        runtime = _runtime()
        with patch("domain_checks.dispatch_workflow.execute_dispatch", new=fixture.execute):
            task = asyncio.create_task(run_dispatch(runtime, DispatchRequest("fixture", "fixture", "Fixture")))
            try:
                result = await _cancel_when_entered(task, fixture.entered)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        require(condition=isinstance(result, asyncio.CancelledError), message="parent cancellation lost")
        require(condition=fixture.cleaned and fixture.notices == 0, message="child cleanup or notice changed")
        require(condition=not runtime.records.history and not runtime.records.events, message="cancellation completed")

    @staticmethod
    async def test_transport_failure_remains_failed_after_unsent_notice() -> None:
        """A failed local notice does not turn a dispatch exception into success."""
        fixture = LocalOperation("failure")
        runtime = _runtime()
        with patch("domain_checks.dispatch_workflow.execute_dispatch", new=fixture.execute), \
                patch("domain_checks.dispatch_errors.send_telegram_message", new=fixture.notice):
            await run_dispatch(runtime, DispatchRequest("fixture", "fixture", "Fixture"))
        records = runtime.records.history or []
        require(condition=len(records) == 1 and fixture.notices == 1, message="failure observation missing")
        require(
            condition=records[0]["ok"] is False and records[0]["queue_state"] == "exception",
            message="transport failure became healthy",
        )
