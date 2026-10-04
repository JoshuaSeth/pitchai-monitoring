# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated vitals lifecycle, optional-operation and cancellation contracts."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .dft_test_support import require
from .metrics_web_vitals import measure_web_vitals

if TYPE_CHECKING:
    from playwright.async_api import Browser

    from .event_bus_delivery import JsonObject


@dataclass
class VitalsFixture:
    """A local browser graph whose admitted operations are separately inspectable."""

    browser: Browser
    operations: dict[str, AsyncMock]
    metrics: JsonObject


def _fixture() -> VitalsFixture:
    metrics: JsonObject = {"lcp_ms": 123.5, "cls": 0.0, "inp_ms": None, "errors": []}
    operation_names = (
        "init", "goto", "click", "evaluate", "page_close", "context_close", "new_page", "new_context",
    )
    operations = {name: AsyncMock() for name in operation_names}
    operations["evaluate"].side_effect = [None, metrics]
    page = MagicMock(add_init_script=operations["init"], goto=operations["goto"],
                     click=operations["click"], evaluate=operations["evaluate"], close=operations["page_close"])
    operations["new_page"].return_value = page
    context = MagicMock(new_page=operations["new_page"], close=operations["context_close"])
    operations["new_context"].return_value = context
    browser = cast("Browser", MagicMock(new_context=operations["new_context"]))
    return VitalsFixture(browser, operations, metrics)


class VitalsTests(unittest.IsolatedAsyncioTestCase):
    """No Playwright driver is started; only the supplied mock browser is used."""

    @staticmethod
    async def test_success_preserves_metrics_identity_and_native_options() -> None:
        """The original viewport/load policy, delays and result dictionary survive."""
        fixture = _fixture()
        with patch("domain_checks.metrics_web_vitals.asyncio.sleep", new=AsyncMock()) as sleep:
            result = await measure_web_vitals(domain=" A.INVALID ", url=" https://a.invalid ",
                                              browser=fixture.browser, timeout_seconds=2, post_load_wait_ms=0)
        require(condition=result.ok and result.domain == "a.invalid" and result.metrics is fixture.metrics,
                message="successful metric result changed")
        fixture.operations["new_context"].assert_awaited_once_with(viewport={"width": 1440, "height": 900})
        fixture.operations["goto"].assert_awaited_once_with("https://a.invalid", wait_until="load", timeout=2000)
        fixture.operations["click"].assert_awaited_once_with("body", timeout=2000)
        sleep.assert_awaited_once_with(0.0)
        fixture.operations["page_close"].assert_awaited_once_with()
        fixture.operations["context_close"].assert_awaited_once_with()

    @staticmethod
    async def test_optional_failures_and_non_dictionary_fallback() -> None:
        """Init/interaction/stop errors remain best effort; bad metric shapes remain empty."""
        fixture = _fixture()
        fixture.operations["init"].side_effect = RuntimeError("optional observer")
        fixture.operations["click"].side_effect = RuntimeError("optional interaction")
        fixture.operations["evaluate"].side_effect = [RuntimeError("optional stop"), [1, 2]]
        result = await measure_web_vitals(domain="a", url="u", browser=fixture.browser, post_load_wait_ms=0)
        require(condition=result.ok and result.metrics == {} and result.error is None,
                message="optional operation became a product failure")
        fixture.operations["context_close"].assert_awaited_once_with()

    @staticmethod
    async def test_error_classification_and_partial_admission() -> None:
        """Ordinary failure prefixes and closure match the resource admission boundary."""
        for error, infrastructure in ((ValueError("ordinary"), False),
                                      (PlaywrightError("browser has been closed"), True),
                                      (PlaywrightTimeoutError("navigation timeout"), False)):
            fixture = _fixture()
            fixture.operations["goto"].side_effect = error
            result = await measure_web_vitals(domain="a", url="u", browser=fixture.browser)
            require(condition=not result.ok and result.error == f"{type(error).__name__}: {error}",
                    message="ordinary failure result changed")
            require(condition=result.browser_infra_error == infrastructure,
                    message="failure classification changed")
            fixture.operations["page_close"].assert_awaited_once_with()
            fixture.operations["context_close"].assert_awaited_once_with()
        fixture = _fixture()
        fixture.operations["new_page"].side_effect = ValueError("page unavailable")
        result = await measure_web_vitals(domain="a", url="u", browser=fixture.browser)
        require(condition=not result.ok, message="partial admission became success")
        fixture.operations["page_close"].assert_not_awaited()
        fixture.operations["context_close"].assert_awaited_once_with()

    @staticmethod
    async def test_read_cancellation_closes_and_cleanup_cancellation_propagates() -> None:
        """Read cancellation closes admitted resources; close cancellation keeps its boundary."""
        for operation in ("goto", "page_close"):
            fixture = _fixture()
            fixture.operations[operation].side_effect = asyncio.CancelledError
            result = await asyncio.gather(measure_web_vitals(
                domain="a", url="u", browser=fixture.browser, post_load_wait_ms=0,
            ), return_exceptions=True)
            require(condition=isinstance(result[0], asyncio.CancelledError), message="cancellation consumed")
            fixture.operations["page_close"].assert_awaited_once_with()
            if operation == "goto":
                fixture.operations["context_close"].assert_awaited_once_with()
            else:
                fixture.operations["context_close"].assert_not_awaited()
