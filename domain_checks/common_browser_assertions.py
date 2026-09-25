# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser-page assertions for domain checks."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, NamedTuple, cast
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from domain_checks.common_text import find_forbidden_text, normalize_text, safe_url

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page, Response

    from domain_checks.common_models import DomainCheckSpec
    from domain_checks.types import JsonObject, JsonValue

_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX_EXCLUSIVE = 300


class _PageSnapshot(NamedTuple):
    status: int | None
    title: str
    title_ok: bool
    final_host: str
    expected_suffix: str
    final_host_ok: bool
    body_text: str


class _SelectorSnapshot(NamedTuple):
    missing_all: list[JsonValue]
    any_candidates: list[JsonValue]
    any_ok: bool
    missing_text: list[JsonValue]


async def _page_snapshot(
    spec: DomainCheckSpec,
    page: Page,
    response: Response | None,
) -> _PageSnapshot:
    status = response.status if response else None
    title = await page.title()
    title_ok = not spec.expected_title_contains or (spec.expected_title_contains.lower() in title.lower())
    final_host = (urlsplit(page.url).hostname or "").lower()
    expected_suffix = (spec.expected_final_host_suffix or "").strip().lower()
    final_host_ok = not expected_suffix or (bool(final_host) and final_host.endswith(expected_suffix))
    body_text = normalize_text(await page.locator("body").inner_text())
    return _PageSnapshot(
        status=status,
        title=title,
        title_ok=title_ok,
        final_host=final_host,
        expected_suffix=expected_suffix,
        final_host_ok=final_host_ok,
        body_text=body_text,
    )


async def _missing_required_all(
    spec: DomainCheckSpec,
    page: Page,
    timeout_ms: int,
) -> list[JsonValue]:
    missing: list[JsonValue] = []
    for check in spec.required_selectors_all:
        try:
            _ = await page.wait_for_selector(
                check.selector,
                state=check.state,
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError:
            missing.append(check.selector)
    return missing


async def _completed_selector_succeeded(
    completed: set[asyncio.Task[ElementHandle | None]],
) -> bool:
    for task in completed:
        try:
            await task
        except PlaywrightError:
            continue
        return True
    return False


async def _wait_for_required_any(
    tasks: list[asyncio.Task[ElementHandle | None]],
    timeout_seconds: float,
) -> bool:
    pending = set(tasks)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while pending:
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        if remaining <= 0:
            return False
        completed, pending = await asyncio.wait(
            pending,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not completed:
            return False
        if await _completed_selector_succeeded(completed):
            return True
    return False


async def _cancel_selector_tasks(
    tasks: list[asyncio.Task[ElementHandle | None]],
) -> None:
    for task in tasks:
        if not task.done():
            _ = task.cancel()
    _ = await asyncio.gather(*tasks, return_exceptions=True)


async def _required_any_ok(
    spec: DomainCheckSpec,
    page: Page,
    timeout_ms: int,
) -> bool:
    if not spec.required_selectors_any:
        return True
    tasks = [
        asyncio.create_task(
            page.wait_for_selector(
                check.selector,
                state=check.state,
                timeout=timeout_ms,
            ),
        )
        for check in spec.required_selectors_any
    ]
    try:
        return await _wait_for_required_any(tasks, timeout_ms / 1000.0)
    finally:
        await _cancel_selector_tasks(tasks)


async def _selector_snapshot(
    spec: DomainCheckSpec,
    page: Page,
    body_text: str,
    timeout_ms: int,
) -> _SelectorSnapshot:
    missing_all = await _missing_required_all(spec, page, timeout_ms)
    any_candidates: list[JsonValue] = [check.selector for check in spec.required_selectors_any]
    any_ok = await _required_any_ok(spec, page, timeout_ms)
    missing_text = cast(
        "list[JsonValue]",
        [expected_text for expected_text in spec.required_text_all if normalize_text(expected_text) not in body_text],
    )
    return _SelectorSnapshot(
        missing_all=missing_all,
        any_candidates=any_candidates,
        any_ok=any_ok,
        missing_text=missing_text,
    )


def _status_ok(spec: DomainCheckSpec, status: int | None) -> bool:
    if status is None:
        return False
    if spec.allowed_status_codes is not None:
        return status in spec.allowed_status_codes
    return _HTTP_SUCCESS_MIN <= status < _HTTP_SUCCESS_MAX_EXCLUSIVE


def _outcome_ok(
    spec: DomainCheckSpec,
    page_snapshot: _PageSnapshot,
    selector_snapshot: _SelectorSnapshot,
    forbidden_hits: list[str],
) -> bool:
    return all(
        (
            _status_ok(spec, page_snapshot.status),
            page_snapshot.title_ok,
            page_snapshot.final_host_ok,
            not forbidden_hits,
            not selector_snapshot.missing_all,
            selector_snapshot.any_ok,
            not selector_snapshot.missing_text,
        ),
    )


async def evaluate_browser_page(
    spec: DomainCheckSpec,
    page: Page,
    response: Response | None,
    *,
    timeout_ms: int,
    started: float,
) -> tuple[bool, JsonObject]:
    """Evaluate all configured assertions against a navigated browser page.

    Returns:
        The overall assertion result and its diagnostic details.
    """
    snapshot = await _page_snapshot(spec, page, response)
    selectors = await _selector_snapshot(spec, page, snapshot.body_text, timeout_ms)
    forbidden_hits = find_forbidden_text(snapshot.body_text, spec.forbidden_text_any)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return _outcome_ok(spec, snapshot, selectors, forbidden_hits), {
        "final_url": safe_url(page.url),
        "final_host": snapshot.final_host,
        "expected_final_host_suffix": snapshot.expected_suffix or None,
        "final_host_ok": snapshot.final_host_ok,
        "http_status": snapshot.status,
        "title": snapshot.title,
        "title_ok": snapshot.title_ok,
        "forbidden_hits": forbidden_hits,
        "missing_selectors_all": selectors.missing_all,
        "required_any_selectors": selectors.any_candidates,
        "required_any_ok": selectors.any_ok,
        "missing_text": selectors.missing_text,
        "browser_elapsed_ms": round(elapsed_ms, 3),
    }
