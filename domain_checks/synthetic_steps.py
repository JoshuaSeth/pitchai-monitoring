# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict step execution for browser-based synthetic transactions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from domain_checks.common_env import substitute_env_refs
from domain_checks.synthetic_models import SyntheticStepContext
from domain_checks.types import JsonObject

if TYPE_CHECKING:
    from collections.abc import Sequence

    from domain_checks.types import JsonValue

type SelectorState = Literal["attached", "detached", "hidden", "visible"]
type StepResult = Awaitable[None] | None
type StepHandler = Callable[[Page, JsonObject, SyntheticStepContext], StepResult]


def _required_integer(value: JsonValue, *, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        message = f"{description} requires an integer"
        raise TypeError(message)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        message = f"{description} requires an integer"
        raise ValueError(message) from exc


def _selector_state(value: JsonValue) -> SelectorState:
    if value is None:
        return "visible"
    if value in {"attached", "detached", "hidden", "visible"}:
        return cast("SelectorState", value)
    message = f"Invalid selector state: {value!r}"
    raise ValueError(message)


def _required_text(step: JsonObject, key: str, description: str) -> str:
    value = str(step.get(key) or "").strip()
    if value:
        return value
    message = f"{description} requires {key}"
    raise ValueError(message)


async def _goto(page: Page, step: JsonObject, context: SyntheticStepContext) -> None:
    url = str(step.get("url") or "").strip() or context.base_url
    if url.startswith("/"):
        url = urljoin(context.base_url.rstrip("/") + "/", url.lstrip("/"))
    _ = await page.goto(
        substitute_env_refs(url),
        wait_until="domcontentloaded",
        timeout=context.timeout_ms,
    )


async def _click(page: Page, step: JsonObject, context: SyntheticStepContext) -> None:
    selector = _required_text(step, "selector", "click")
    await page.click(selector, timeout=context.timeout_ms)


async def _fill(page: Page, step: JsonObject, context: SyntheticStepContext) -> None:
    selector = _required_text(step, "selector", "fill")
    text = substitute_env_refs(str(step.get("text") or ""))
    await page.fill(selector, text, timeout=context.timeout_ms)


async def _press(page: Page, step: JsonObject, context: SyntheticStepContext) -> None:
    selector = str(step.get("selector") or "").strip()
    key = str(step.get("key") or "").strip() or "Enter"
    if selector:
        await page.press(selector, key, timeout=context.timeout_ms)
    else:
        await page.keyboard.press(key)


async def _wait_for_selector(
    page: Page,
    step: JsonObject,
    context: SyntheticStepContext,
) -> None:
    selector = _required_text(step, "selector", "wait_for_selector")
    _ = await page.wait_for_selector(
        selector,
        state=_selector_state(step.get("state")),
        timeout=context.timeout_ms,
    )


def _expect_url(
    page: Page,
    step: JsonObject,
    _context: SyntheticStepContext,
) -> None:
    expected = _required_text(step, "value", "expect_url_contains")
    if expected not in (page.url or ""):
        message = f"url_missing_substring: {expected!r} not in {page.url!r}"
        raise AssertionError(message)


async def _expect_text(
    page: Page,
    step: JsonObject,
    _context: SyntheticStepContext,
) -> None:
    expected = _required_text(step, "text", "expect_text")
    body = await page.locator("body").inner_text()
    if expected.lower() not in body.lower():
        message = f"text_missing: {expected!r}"
        raise AssertionError(message)


async def _expect_title(
    page: Page,
    step: JsonObject,
    _context: SyntheticStepContext,
) -> None:
    raw_text = step.get("text") or step.get("value")
    expected = str(raw_text or "").strip()
    if not expected:
        message = "expect_title_contains requires text/value"
        raise ValueError(message)
    title = await page.title()
    if expected.lower() not in str(title or "").lower():
        message = f"title_missing_substring: {expected!r} not in {title!r}"
        raise AssertionError(message)


async def _expect_selector_count(
    page: Page,
    step: JsonObject,
    _context: SyntheticStepContext,
) -> None:
    selector = _required_text(step, "selector", "expect_selector_count")
    expected = _required_integer(
        step.get("count"),
        description="expect_selector_count",
    )
    actual = await page.locator(selector).count()
    if actual != expected:
        message = f"selector_count_mismatch: selector={selector!r} got={actual} expected={expected}"
        raise AssertionError(message)


async def _set_viewport(
    page: Page,
    step: JsonObject,
    _context: SyntheticStepContext,
) -> None:
    width = _required_integer(step.get("width"), description="set_viewport width")
    height = _required_integer(step.get("height"), description="set_viewport height")
    await page.set_viewport_size({"width": width, "height": height})


def _screenshot_name(step: JsonObject) -> str:
    name = str(step.get("name") or "screenshot").strip() or "screenshot"
    safe_name = "".join(character for character in name if character.isalnum() or character in {"-", "_"})[:60]
    return safe_name or "screenshot"


async def _screenshot(
    page: Page,
    step: JsonObject,
    context: SyntheticStepContext,
) -> None:
    if not context.artifacts_dir:
        return
    safe_name = _screenshot_name(step)
    filename = f"{safe_name}.png"
    path = str(Path(context.artifacts_dir) / filename)
    try:
        _ = await page.screenshot(path=path, full_page=True)
    except PlaywrightError:
        logging.getLogger(__name__).warning(
            "Unable to capture synthetic-monitor screenshot",
            exc_info=True,
        )
    else:
        context.artifact_names[f"screenshot_{safe_name}"] = filename


async def _sleep(_page: Page, step: JsonObject, _context: SyntheticStepContext) -> None:
    milliseconds = step.get("ms")
    duration = 250 if milliseconds is None else _required_integer(milliseconds, description="sleep ms")
    await asyncio.sleep(max(0.0, duration / 1000.0))


_STEP_HANDLERS: dict[str, StepHandler] = {
    "click": _click,
    "expect_selector_count": _expect_selector_count,
    "expect_text": _expect_text,
    "expect_title_contains": _expect_title,
    "expect_url_contains": _expect_url,
    "fill": _fill,
    "goto": _goto,
    "press": _press,
    "screenshot": _screenshot,
    "set_viewport": _set_viewport,
    "sleep": _sleep,
    "sleep_ms": _sleep,
    "wait_for_selector": _wait_for_selector,
}


async def execute_synthetic_steps(
    page: Page,
    steps: Sequence[JsonValue],
    context: SyntheticStepContext,
) -> None:
    """Validate and execute at most sixty configured transaction steps.

    Raises:
        TypeError: A configured step is not a mapping or uses an invalid type.
        ValueError: A configured step is missing required values or is unknown.
    """
    for raw_step in steps[:60]:
        if not isinstance(raw_step, dict):
            message = f"Invalid step: {raw_step!r}"
            raise TypeError(message)
        step_type = str(raw_step.get("type") or "").strip().lower()
        if not step_type:
            message = f"Missing step.type: {raw_step!r}"
            raise ValueError(message)
        handler = _STEP_HANDLERS.get(step_type)
        if handler is None:
            message = f"Unknown step.type: {step_type!r}"
            raise ValueError(message)
        result = handler(page, raw_step, context)
        if result is not None:
            await result
