# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated transaction limits, failure artifacts and cancellation contracts."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import Error as PlaywrightError

from .dft_test_support import require
from .metrics_synthetic import run_synthetic_transactions
from .synthetic_artifacts import SyntheticArtifacts
from .synthetic_steps import SyntheticSteps
from .synthetic_values import substitute_env_refs

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

    from .event_bus_delivery import JsonValue


class SyntheticTests(unittest.IsolatedAsyncioTestCase):
    """Every browser method is synthetic; no driver, HTTP client or socket is used."""

    @staticmethod
    async def test_skip_limit_and_sequential_failure_results() -> None:
        """Malformed transactions skip; valid ones run in order and stop at sixty steps."""
        click = AsyncMock()
        page_close = AsyncMock()
        page = MagicMock(url="https://a.invalid/", click=click, close=page_close)
        context_close = AsyncMock()
        context = MagicMock(new_page=AsyncMock(return_value=page), route=AsyncMock(), close=context_close)
        create = AsyncMock(return_value=context)
        browser = cast("Browser", MagicMock(new_context=create))
        click_steps: list[JsonValue] = [{"type": "click", "selector": "button"}] * 61
        inputs: list[JsonValue] = [None, {}, {"steps": []}, {"steps": "bad"},
                                  {"name": "fails", "steps": [None]},
                                  {"name": "succeeds", "steps": click_steps}]
        results = await run_synthetic_transactions(domain=" A.INVALID ", base_url="u", browser=browser,
                                                   transactions=inputs)
        require(condition=[result.ok for result in results] == [False, True], message="result ordering changed")
        expected_limit = 60
        require(condition=click.await_count == expected_limit, message="step bound changed")
        require(condition=results[0].error == "ValueError: Invalid step: None", message="error contract changed")
        require(condition="title" not in results[0].details and results[1].domain == "a.invalid",
                message="ordinary error acquired a title or normalization changed")
        expected_transactions = 2
        require(condition=create.await_count == page_close.await_count == context_close.await_count
                == expected_transactions, message="transaction resource count changed")

    @staticmethod
    async def test_native_failure_retains_title_and_local_log_intent() -> None:
        """Playwright failures retain title before screenshot/trace/log handling."""
        page = MagicMock(url="https://a.invalid/fail", goto=AsyncMock(side_effect=PlaywrightError("failed")),
                         title=AsyncMock(return_value="title"), screenshot=AsyncMock(), close=AsyncMock())
        tracing = MagicMock(start=AsyncMock(), stop=AsyncMock())
        context = MagicMock(new_page=AsyncMock(return_value=page), route=AsyncMock(),
                            close=AsyncMock(), tracing=tracing)
        browser = cast("Browser", MagicMock(new_context=AsyncMock(return_value=context)))
        with patch("domain_checks.synthetic_artifacts.write_artifact") as write:
            results = await run_synthetic_transactions(domain="a", base_url="u", browser=browser,
                transactions=[{"steps": [{"type": "goto"}]}], artifacts_dir="synthetic", trace_on_failure=True)
        require(condition=results[0].details == {
            "final_url": "https://a.invalid/fail", "title": "title", "failure_screenshot": "failure.png",
            "trace_zip": "trace.zip", "run_log": "run.log",
        }, message="failure artifact contract changed")
        write.assert_called_once()

    @staticmethod
    async def test_trace_export_failure_attempts_plain_stop() -> None:
        """A failed optional export retains failure identity and attempts the original stop."""
        stop = AsyncMock(side_effect=[ValueError("export failed"), None])
        context = cast("BrowserContext", MagicMock(tracing=MagicMock(stop=stop)))
        artifacts = SyntheticArtifacts("synthetic", tracing_started=True)
        await artifacts.failure(None, context)
        expected_attempts = 2
        require(condition=stop.await_count == expected_attempts and not artifacts.names,
                message="failed export recorded a file or skipped stop")

    @staticmethod
    async def test_cancellation_is_not_a_transaction_failure() -> None:
        """Cancellation propagates while releasing the admitted page before its context."""
        close = AsyncMock()
        page = MagicMock(goto=AsyncMock(side_effect=asyncio.CancelledError), close=close)
        context_close = AsyncMock()
        context = MagicMock(new_page=AsyncMock(return_value=page), route=AsyncMock(), close=context_close)
        browser = cast("Browser", MagicMock(new_context=AsyncMock(return_value=context)))
        outcomes = await asyncio.gather(run_synthetic_transactions(
            domain="a", base_url="u", browser=browser, transactions=[{"steps": [{"type": "goto"}]}],
        ), return_exceptions=True)
        require(condition=isinstance(outcomes[0], asyncio.CancelledError), message="cancellation was classified")
        close.assert_awaited_once_with()
        context_close.assert_awaited_once_with()

    @staticmethod
    async def test_environment_resolution_precedes_selector_failure() -> None:
        """Missing environment values keep their original precedence over empty selectors."""
        page = cast("Page", MagicMock())
        steps = SyntheticSteps(page, "u", 1000, SyntheticArtifacts(None))
        with patch("domain_checks.synthetic_values.os.getenv", return_value=None):
            result = await asyncio.gather(steps.run({"type": "fill", "text": "${D31_TEST}"}),
                                          return_exceptions=True)
        require(condition=isinstance(result[0], ValueError)
                and str(result[0]) == "missing_env_secrets: ['D31_TEST']", message="validation precedence changed")
        with patch("domain_checks.synthetic_values.os.getenv", return_value="local"):
            require(condition=substitute_env_refs("a${D31_TEST}b") == "alocalb", message="substitution changed")
