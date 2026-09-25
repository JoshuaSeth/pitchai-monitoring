# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lifecycle orchestration for browser-based synthetic transactions."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Unpack

from playwright.async_api import Error as PlaywrightError

from domain_checks.common_browser_runtime import (
    install_resource_filter,
    is_browser_infrastructure_error,
)
from domain_checks.synthetic_artifacts import failure_details, safe_string
from domain_checks.synthetic_models import (
    SyntheticRunSettings,
    SyntheticSession,
    SyntheticStepContext,
    SyntheticTransactionResult,
)
from domain_checks.synthetic_steps import execute_synthetic_steps

if TYPE_CHECKING:
    from collections.abc import Sequence

    from playwright.async_api import Browser, BrowserContext, Page

    from domain_checks.synthetic_models import (
        SyntheticRunOptions,
    )
    from domain_checks.types import JsonObject, JsonValue

LOGGER = logging.getLogger(__name__)


def _run_settings(
    domain: str,
    base_url: str,
    browser: Browser,
    options: SyntheticRunOptions,
) -> SyntheticRunSettings:
    timeout_seconds = options.get("timeout_seconds", 35.0)
    return SyntheticRunSettings(
        domain=str(domain or "").strip().lower(),
        base_url=str(base_url or "").strip(),
        browser=browser,
        timeout_ms=int(max(1.0, float(timeout_seconds)) * 1000),
        artifacts_dir=options.get("artifacts_dir"),
        trace_on_failure=options.get("trace_on_failure", False),
    )


async def _start_trace(
    session: SyntheticSession,
    settings: SyntheticRunSettings,
) -> None:
    if not settings.trace_on_failure or not settings.artifacts_dir:
        return
    if session.context is None:
        message = "Synthetic context missing before trace start"
        raise RuntimeError(message)
    try:
        await session.context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=False,
        )
    except PlaywrightError:
        LOGGER.debug(
            "Unable to start synthetic-monitor tracing",
            exc_info=True,
        )
        return
    session.tracing_started = True


async def _open_session(
    session: SyntheticSession,
    settings: SyntheticRunSettings,
) -> None:
    session.context = await settings.browser.new_context(
        viewport={"width": 1280, "height": 720},
    )
    await install_resource_filter(
        session.context,
        failure_message="Unable to install synthetic-monitor resource filter",
    )
    session.page = await session.context.new_page()
    await _start_trace(session, settings)


def _open_resources(session: SyntheticSession) -> tuple[BrowserContext, Page]:
    if session.context is None or session.page is None:
        message = "Synthetic session resources are not open"
        raise RuntimeError(message)
    return session.context, session.page


async def _stop_success_trace(session: SyntheticSession) -> None:
    if not session.tracing_started or session.context is None:
        return
    try:
        await session.context.tracing.stop()
    except PlaywrightError:
        LOGGER.debug(
            "Unable to stop successful synthetic-monitor trace",
            exc_info=True,
        )


async def _close_page(page: Page) -> None:
    try:
        await page.close()
    except PlaywrightError:
        LOGGER.debug("Unable to close synthetic-monitor page", exc_info=True)


async def _close_context(context: BrowserContext) -> None:
    try:
        await context.close()
    except PlaywrightError:
        LOGGER.debug("Unable to close synthetic-monitor context", exc_info=True)


async def _close_session(session: SyntheticSession) -> None:
    if session.page is not None:
        await _close_page(session.page)
    if session.context is not None:
        await _close_context(session.context)


def _success_result(
    settings: SyntheticRunSettings,
    session: SyntheticSession,
    name: str,
    started: float,
) -> SyntheticTransactionResult:
    _context, page = _open_resources(session)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return SyntheticTransactionResult(
        domain=settings.domain,
        name=name,
        ok=True,
        elapsed_ms=round(elapsed_ms, 3),
        error=None,
        details={"final_url": safe_string(page.url), **session.artifact_names},
        browser_infra_error=False,
    )


async def _failure_result(
    settings: SyntheticRunSettings,
    session: SyntheticSession,
    name: str,
    started: float,
    exc: Exception,
) -> SyntheticTransactionResult:
    infrastructure_error = is_browser_infrastructure_error(exc)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    error_text = f"{type(exc).__name__}: {exc}"
    details = await failure_details(
        session,
        settings,
        error_text,
        browser_infra_error=infrastructure_error,
    )
    return SyntheticTransactionResult(
        domain=settings.domain,
        name=name,
        ok=False,
        elapsed_ms=round(elapsed_ms, 3),
        error=error_text,
        details=details,
        browser_infra_error=infrastructure_error,
    )


async def _execute_open_transaction(
    settings: SyntheticRunSettings,
    session: SyntheticSession,
    name: str,
    steps: Sequence[JsonValue],
    started: float,
) -> SyntheticTransactionResult:
    await _open_session(session, settings)
    _context, page = _open_resources(session)
    step_context = SyntheticStepContext(
        base_url=settings.base_url,
        timeout_ms=settings.timeout_ms,
        artifacts_dir=settings.artifacts_dir,
        artifact_names=session.artifact_names,
    )
    await execute_synthetic_steps(page, steps, step_context)
    result = _success_result(settings, session, name, started)
    await _stop_success_trace(session)
    return result


async def _run_transaction(
    settings: SyntheticRunSettings,
    name: str,
    steps: Sequence[JsonValue],
) -> SyntheticTransactionResult:
    started = time.perf_counter()
    session = SyntheticSession()
    try:
        result = await _execute_open_transaction(
            settings,
            session,
            name,
            steps,
            started,
        )
    except (PlaywrightError, AssertionError, TypeError, ValueError) as exc:
        return await _failure_result(settings, session, name, started, exc)
    else:
        return result
    finally:
        await _close_session(session)


async def run_synthetic_transactions(
    *,
    domain: str,
    base_url: str,
    browser: Browser,
    transactions: Sequence[JsonObject],
    **options: Unpack[SyntheticRunOptions],
) -> list[SyntheticTransactionResult]:
    """Run each valid configured synthetic transaction in an isolated context.

    Returns:
        Transaction outcomes in configuration order.
    """
    settings = _run_settings(domain, base_url, browser, options)
    results: list[SyntheticTransactionResult] = []
    for transaction in transactions:
        steps = transaction.get("steps")
        if not isinstance(steps, list) or not steps:
            continue
        name = str(transaction.get("name") or "transaction").strip()[:120]
        results.append(await _run_transaction(settings, name, steps))
    return results
