# Copyright (c) 2026 PitchAI. All rights reserved.
"""Failure evidence capture for synthetic transactions."""

from __future__ import annotations

import json
import logging
import pathlib
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

if TYPE_CHECKING:
    from domain_checks.synthetic_models import SyntheticRunSettings, SyntheticSession
    from domain_checks.types import JsonObject

LOGGER = logging.getLogger(__name__)


def safe_string(value: str | None, *, max_len: int = 500) -> str:
    """Bound a value before including it in monitoring evidence.

    Returns:
        The bounded string.
    """
    text = value or ""
    return text if len(text) <= max_len else text[:max_len]


def _persist_artifact(path: pathlib.Path, content: str) -> None:
    resolved_path = path.resolve()
    resolved_path.parent.mkdir(exist_ok=True, parents=True)
    _ = resolved_path.write_text(content, encoding="utf-8")


def _write_artifact(path: pathlib.Path, content: str) -> None:
    try:
        _persist_artifact(path, content)
    except OSError:
        LOGGER.warning(
            "Unable to write synthetic-monitor artifact %s",
            path,
            exc_info=True,
        )


async def _failed_title(session: SyntheticSession) -> str | None:
    if session.page is None:
        return None
    try:
        return await session.page.title()
    except PlaywrightError:
        LOGGER.debug(
            "Unable to read the failed synthetic page title",
            exc_info=True,
        )
        return None


def _prepare_artifact_root(path: str) -> pathlib.Path | None:
    root = pathlib.Path(path).resolve()
    try:
        root.mkdir(exist_ok=True, parents=True)
    except OSError:
        LOGGER.warning(
            "Unable to create synthetic-monitor artifact directory",
            exc_info=True,
        )
        return None
    return root


async def _capture_failure_screenshot(
    session: SyntheticSession,
    artifact_root: pathlib.Path,
) -> None:
    if session.page is None:
        return
    failure_name = "failure.png"
    try:
        _ = await session.page.screenshot(
            path=str(artifact_root / failure_name),
            full_page=True,
        )
    except PlaywrightError:
        LOGGER.warning(
            "Unable to capture failed synthetic-monitor page",
            exc_info=True,
        )
    else:
        session.artifact_names["failure_screenshot"] = failure_name


async def _stop_failed_trace(
    session: SyntheticSession,
    artifact_root: pathlib.Path,
) -> None:
    if not session.tracing_started or session.context is None:
        return
    trace_name = "trace.zip"
    try:
        await session.context.tracing.stop(path=str(artifact_root / trace_name))
    except PlaywrightError:
        LOGGER.warning(
            "Unable to export failed synthetic-monitor trace",
            exc_info=True,
        )
        try:
            await session.context.tracing.stop()
        except PlaywrightError:
            LOGGER.debug(
                "Unable to stop failed synthetic-monitor trace",
                exc_info=True,
            )
    else:
        session.artifact_names["trace_zip"] = trace_name


def _failure_log(
    session: SyntheticSession,
    title: str | None,
    error_text: str,
    *,
    browser_infra_error: bool,
) -> str:
    data: JsonObject = {
        "error": error_text,
        "final_url": safe_string(session.page.url) if session.page is not None else None,
        "title": safe_string(title) if title is not None else None,
        "browser_infra_error": browser_infra_error,
    }
    return safe_string(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2),
        max_len=50_000,
    )


async def failure_details(
    session: SyntheticSession,
    settings: SyntheticRunSettings,
    error_text: str,
    *,
    browser_infra_error: bool,
) -> JsonObject:
    """Capture configured failure evidence and return bounded result details.

    Returns:
        Bounded page and artifact details for the failed transaction.
    """
    title = await _failed_title(session)
    if settings.artifacts_dir:
        artifact_root = _prepare_artifact_root(settings.artifacts_dir)
        if artifact_root is not None:
            await _capture_failure_screenshot(session, artifact_root)
            await _stop_failed_trace(session, artifact_root)
            _write_artifact(
                artifact_root / "run.log",
                _failure_log(
                    session,
                    title,
                    error_text,
                    browser_infra_error=browser_infra_error,
                ),
            )
            _ = session.artifact_names.setdefault("run_log", "run.log")
    return {
        "final_url": safe_string(session.page.url) if session.page is not None else None,
        "title": safe_string(title) if title is not None else None,
        **session.artifact_names,
    }
