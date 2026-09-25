# Copyright (c) 2026 PitchAI. All rights reserved.
"""Failure artifacts owned by the submitted-test sandbox process."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

from e2e_sandbox.errors import safe_text

if TYPE_CHECKING:
    from pathlib import Path

    from e2e_sandbox.browser_session import BrowserSession
    from e2e_sandbox.models import RunResult, SandboxRequest

_MAXIMUM_TRACEBACK_LENGTH = 50_000
LOGGER = logging.getLogger("e2e-sandbox")


def _write_run_log(
    *,
    path: Path,
    result: RunResult,
    error: Exception,
) -> None:
    payload = {
        "status": result.status,
        "error_kind": result.error_kind,
        "error_message": result.error_message,
        "final_url": result.final_url,
        "title": result.title,
        "browser_infra_error": result.browser_infra_error,
        "traceback": safe_text(
            "".join(traceback.format_exception(error)),
            maximum_length=_MAXIMUM_TRACEBACK_LENGTH,
        ),
    }
    encoded_payload = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    _ = path.write_text(encoded_payload, encoding="utf-8")


async def failure_artifacts(
    *,
    session: BrowserSession | None,
    request: SandboxRequest,
    result: RunResult,
    error: Exception,
) -> dict[str, str]:
    """Capture every available bounded artifact for one failed invocation.

    Returns:
        Artifact field names mapped to their relative filenames.
    """
    artifacts: dict[str, str] = {}
    if session is not None:
        screenshot_name = await _capture_failure_screenshot(session, request)
        if screenshot_name is not None:
            artifacts["failure_screenshot"] = screenshot_name
        if session.tracing_started:
            trace_name = await _capture_failure_trace(session, request)
            if trace_name is not None:
                artifacts["trace_zip"] = trace_name
    log_written = await _write_failure_log(request=request, result=result, error=error)
    if log_written:
        artifacts["run_log"] = "run.log"
    return artifacts


async def _capture_failure_screenshot(
    session: BrowserSession,
    request: SandboxRequest,
) -> str | None:
    screenshot_name = "failure.png"
    try:
        await session.page.screenshot(
            path=str(request.artifacts_dir / screenshot_name),
            full_page=True,
        )
    except (OSError, RuntimeError, PlaywrightError):
        LOGGER.exception("Failed to capture submitted-test screenshot")
        return None
    return screenshot_name


async def _capture_failure_trace(
    session: BrowserSession,
    request: SandboxRequest,
) -> str | None:
    trace_name = "trace.zip"
    try:
        await session.context.tracing.stop(path=str(request.artifacts_dir / trace_name))
    except (OSError, RuntimeError, PlaywrightError):
        LOGGER.exception("Failed to capture submitted-test trace")
        return None
    return trace_name


async def _write_failure_log(
    *,
    request: SandboxRequest,
    result: RunResult,
    error: Exception,
) -> bool:
    try:
        await asyncio.to_thread(
            _write_run_log,
            path=request.artifacts_dir / "run.log",
            result=result,
            error=error,
        )
    except OSError:
        LOGGER.exception("Failed to write submitted-test failure log")
        return False
    return True
