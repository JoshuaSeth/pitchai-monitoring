# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic observation classification, precedence and semaphore lifecycle."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from .common_check import DomainCheckSpec
from .dft_test_support import require
from .domain_observation import DomainProbes, observe_domain

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


class DomainObservationTests(unittest.IsolatedAsyncioTestCase):
    """All HTTP/browser functions are replaced; no transport exists."""

    @staticmethod
    async def test_classification_and_detail_precedence() -> None:
        """HTTP failure wins; explicit contracts skip browser; infrastructure stays distinct."""
        cases = (
            (False, True, True, False, False, False, "http_check_failed"),
            (True, False, True, False, False, True, "browser_not_applicable"),
            (True, True, False, False, False, True, "browser_degraded"),
            (True, True, True, False, False, False, "browser_check_failed"),
            (True, True, True, False, True, True, "browser_degraded"),
            (True, True, True, True, True, True, "ok"),
        )
        for http_ok, enabled, available, browser_ok, infra, expected_ok, reason in cases:
            spec = DomainCheckSpec("fixture.invalid", "https://fixture.invalid", browser_enabled=enabled)
            http_details: JsonObject = {"status_code": 200, "error": "http marker"}
            browser_details: JsonObject = {"browser_infra_error": infra, "error": "browser marker"}
            check = AsyncMock(return_value=(browser_ok, browser_details))
            result = await observe_domain(
                spec, MagicMock(spec=AsyncClient), "synthetic-handle" if available else None,
                browser_semaphore=asyncio.Semaphore(1),
                probes=DomainProbes[str](AsyncMock(return_value=(http_ok, http_details)), check),
            )
            require(condition=result.ok is expected_ok and result.reason == reason, message="classification changed")
            called = http_ok and enabled and available
            require(condition=check.await_count == int(called), message="browser admission changed")
            if called:
                require(condition=cast("JsonObject", result.details)["error"] == "browser marker",
                        message="merge precedence changed")
            if not http_ok:
                require(condition=result.details is http_details, message="HTTP failure mapping copied")
            require(condition=http_details["error"] == "http marker", message="input details mutated")

    @staticmethod
    async def test_cancellation_releases_browser_permit() -> None:
        """A cancelled observation runs its browser cleanup and returns the semaphore slot."""
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def blocked_browser(_spec: DomainCheckSpec, _browser: str) -> tuple[bool, JsonObject]:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
            return True, {}

        semaphore = asyncio.Semaphore(1)
        spec = DomainCheckSpec("fixture.invalid", "https://fixture.invalid")
        probes = DomainProbes[str](AsyncMock(return_value=(True, {})), blocked_browser)
        task = asyncio.create_task(observe_domain(spec, MagicMock(spec=AsyncClient), "synthetic-handle",
                                                  browser_semaphore=semaphore, probes=probes))
        await asyncio.wait_for(entered.wait(), timeout=1)
        _ = task.cancel("synthetic cancellation")
        try:
            await task
        except asyncio.CancelledError as caught:
            require(condition=str(caught) == "synthetic cancellation", message="cancellation message lost")
        else:
            require(condition=False, message="cancellation swallowed")
        require(condition=cleaned.is_set() and not semaphore.locked(), message="cancelled check leaked permit")

    @staticmethod
    async def test_browser_exception_releases_permit_without_false_result() -> None:
        """Unexpected checks propagate to the cycle's existing crash classifier."""
        failure = RuntimeError("synthetic browser crash")
        semaphore = asyncio.Semaphore(1)
        spec = DomainCheckSpec("fixture.invalid", "https://fixture.invalid")
        probes = DomainProbes[str](AsyncMock(return_value=(True, {})), AsyncMock(side_effect=failure))
        try:
            await observe_domain(spec, MagicMock(spec=AsyncClient), "synthetic-handle",
                                 browser_semaphore=semaphore, probes=probes)
        except RuntimeError as caught:
            require(condition=caught is failure, message="failure replaced")
        else:
            require(condition=False, message="failure swallowed")
        require(condition=not semaphore.locked(), message="failure leaked slot")
