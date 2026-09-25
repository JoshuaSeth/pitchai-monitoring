# Copyright (c) 2026 PitchAI. All rights reserved.
"""Playwright lifecycle and artifact handling for submitted Python tests."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from e2e_sandbox.artifacts import failure_artifacts
from e2e_sandbox.browser_session import close_session, start_session
from e2e_sandbox.errors import EXPECTED_SUBMISSION_ERRORS, is_infrastructure_failure, safe_text
from e2e_sandbox.models import RunResult
from e2e_sandbox.submission import invoke_submission, load_submission

if TYPE_CHECKING:
    from types import ModuleType

    from playwright.async_api import Page, Playwright

    from e2e_sandbox.browser_session import BrowserSession
    from e2e_sandbox.models import SandboxRequest, SandboxStatus

_MAXIMUM_ERROR_LENGTH = 2_000
LOGGER = logging.getLogger("e2e-sandbox")


async def _page_metadata(page: Page) -> tuple[str | None, str | None]:
    final_url = safe_text(page.url, maximum_length=_MAXIMUM_ERROR_LENGTH) or None
    try:
        title_text = await page.title()
    except (OSError, RuntimeError, PlaywrightError):
        LOGGER.exception("Failed to read submitted-test page title")
        title_text = ""
    title = safe_text(title_text, maximum_length=500)
    return final_url, title or None


async def _execute_active_session(
    request: SandboxRequest,
    *,
    started_at: float,
    session: BrowserSession,
    module: ModuleType,
) -> RunResult:
    invocation_error: Exception | None = None
    try:
        await invoke_submission(
            module=module,
            page=session.page,
            base_url=request.base_url,
            artifacts_dir=request.artifacts_dir,
        )
    except EXPECTED_SUBMISSION_ERRORS as error:
        invocation_error = error
    final_url, title = await _page_metadata(session.page)
    elapsed_ms = round((time.perf_counter() - started_at) * 1_000.0, 3)
    if invocation_error is None:
        if session.tracing_started:
            await _stop_success_trace(session)
        return RunResult(
            status="pass",
            elapsed_ms=elapsed_ms,
            error_kind=None,
            error_message=None,
            final_url=final_url,
            title=title,
            artifacts={},
            browser_infra_error=False,
        )

    infrastructure_failure = is_infrastructure_failure(invocation_error)
    status: SandboxStatus = "infra_degraded" if infrastructure_failure else "fail"
    base_result = RunResult(
        status,
        elapsed_ms,
        type(invocation_error).__name__,
        safe_text(invocation_error, maximum_length=_MAXIMUM_ERROR_LENGTH),
        final_url,
        title,
        {},
        infrastructure_failure,
    )
    artifacts = await failure_artifacts(
        session=session,
        request=request,
        result=base_result,
        error=invocation_error,
    )
    return base_result._replace(artifacts=artifacts)


async def _stop_success_trace(session: BrowserSession) -> None:
    try:
        await session.context.tracing.stop()
    except (OSError, RuntimeError, PlaywrightError):
        LOGGER.exception("Failed to stop submitted-test success trace")


async def execute_with_playwright(
    request: SandboxRequest,
    *,
    started_at: float,
    playwright: Playwright,
) -> RunResult:
    """Load verified code before browser startup and always close an opened session.

    Returns:
        The submitted test result after owned browser resources are released.
    """
    module = load_submission(request.test_file)
    session = await start_session(playwright, request)
    try:
        return await _execute_active_session(
            request,
            started_at=started_at,
            session=session,
            module=module,
        )
    finally:
        await close_session(session)


async def execute_submission(request: SandboxRequest) -> RunResult:
    """Execute one submitted test and convert every runtime failure to a result.

    Returns:
        A complete machine-readable sandbox result.
    """
    started_at = time.perf_counter()
    try:
        return await _execute_with_manager(request=request, started_at=started_at)
    except EXPECTED_SUBMISSION_ERRORS as error:
        return await _outer_failure_result(request=request, started_at=started_at, error=error)


async def _execute_with_manager(*, request: SandboxRequest, started_at: float) -> RunResult:
    async with async_playwright() as playwright:
        return await execute_with_playwright(request, started_at=started_at, playwright=playwright)


async def _outer_failure_result(
    *,
    request: SandboxRequest,
    started_at: float,
    error: Exception,
) -> RunResult:
    infrastructure_failure = is_infrastructure_failure(error)
    status: SandboxStatus = "infra_degraded" if infrastructure_failure else "fail"
    base_result = RunResult(
        status,
        round((time.perf_counter() - started_at) * 1_000.0, 3),
        type(error).__name__,
        safe_text(error, maximum_length=_MAXIMUM_ERROR_LENGTH),
        None,
        None,
        {},
        infrastructure_failure,
    )
    artifacts = await failure_artifacts(
        session=None,
        request=request,
        result=base_result,
        error=error,
    )
    return base_result._replace(artifacts=artifacts)
