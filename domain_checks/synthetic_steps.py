# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit synthetic browser actions and assertions with original input precedence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from urllib.parse import urljoin

from .browser_failure import BrowserFailure
from .cycle_values import coerce_int, required_int
from .synthetic_values import substitute_env_refs

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Literal

    from playwright.async_api import Page

    from .event_bus_delivery import JsonObject, JsonValue
    from .synthetic_artifacts import SyntheticArtifacts


@dataclass
class SyntheticSteps:
    """The page, timeout and optional artifacts of one sequential transaction."""

    page: Page
    base: str
    timeout_ms: int
    artifacts: SyntheticArtifacts

    async def run(self, raw: JsonValue) -> None:
        """Dispatch only the original supported action names in their original step order.

        Raises:
            ValueError: A step is malformed or has an unsupported action type.
        """
        match raw:
            case dict() as step:
                await self.dispatch(step)
            case _:
                message = f"Invalid step: {raw!r}"
                raise ValueError(message)

    async def dispatch(self, step: JsonObject) -> None:
        """Validate the action discriminator and execute its original operation.

        Raises:
            ValueError: The discriminator is empty or unsupported.
        """
        kind = str(step.get("type") or "").strip().lower()
        if not kind:
            message = f"Missing step.type: {step!r}"
            raise ValueError(message)
        actions: dict[str, Callable[[JsonObject], Awaitable[None]]] = {
            "goto": self.goto, "click": self.click, "fill": self.fill, "press": self.press,
            "wait_for_selector": self.wait_for_selector, "expect_url_contains": self.expect_url,
            "expect_text": self.expect_text, "expect_title_contains": self.expect_title,
            "expect_selector_count": self.expect_count, "set_viewport": self.set_viewport,
            "screenshot": self.screenshot, "sleep": self.sleep, "sleep_ms": self.sleep,
        }
        action = actions.get(kind)
        if action is None:
            message = f"Unknown step.type: {kind!r}"
            raise ValueError(message)
        await action(step)

    async def goto(self, step: JsonObject) -> None:
        """Preserve relative URL joining before environment substitution."""
        url = str(step.get("url") or "").strip() or self.base
        if url.startswith("/"):
            url = urljoin(self.base.rstrip("/") + "/", url.lstrip("/"))
        url = substitute_env_refs(url)
        _ = await self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)

    async def click(self, step: JsonObject) -> None:
        """Click the original nonempty selector.

        Raises:
            ValueError: The selector is empty.
        """
        selector = str(step.get("selector") or "").strip()
        if not selector:
            message = "click requires selector"
            raise ValueError(message)
        await self.page.click(selector, timeout=self.timeout_ms)

    async def fill(self, step: JsonObject) -> None:
        """Resolve secrets before applying the original selector validation.

        Raises:
            ValueError: The selector is empty or a referenced value is unavailable.
        """
        selector = str(step.get("selector") or "").strip()
        text = substitute_env_refs(str(step.get("text") or ""))
        if not selector:
            message = "fill requires selector"
            raise ValueError(message)
        await self.page.fill(selector, text, timeout=self.timeout_ms)

    async def press(self, step: JsonObject) -> None:
        """Use the selected element or the page keyboard, with the original Enter default."""
        selector = str(step.get("selector") or "").strip()
        key = str(step.get("key") or "").strip() or "Enter"
        if selector:
            await self.page.press(selector, key, timeout=self.timeout_ms)
        else:
            await self.page.keyboard.press(key)

    async def wait_for_selector(self, step: JsonObject) -> None:
        """Delegate state validation to Playwright, retaining its error behavior.

        Raises:
            ValueError: The selector is empty.
        """
        selector = str(step.get("selector") or "").strip()
        state = str(step.get("state") or "visible").strip()
        if not selector:
            message = "wait_for_selector requires selector"
            raise ValueError(message)
        # The native API validates unexpected strings; do not replace its failure.
        native_state = cast('Literal["attached", "detached", "hidden", "visible"]', state)
        _ = await self.page.wait_for_selector(selector, state=native_state, timeout=self.timeout_ms)

    async def expect_url(self, step: JsonObject) -> None:
        """Check the original case-sensitive URL substring.

        Raises:
            ValueError: The expected substring is empty.
            AssertionError: The current URL does not include the substring.
        """
        value = str(step.get("value") or "").strip()
        if not value:
            message = "expect_url_contains requires value"
            raise ValueError(message)
        if value not in (self.page.url or ""):
            message = f"url_missing_substring: {value!r} not in {self.page.url!r}"
            raise AssertionError(message)

    async def expect_text(self, step: JsonObject) -> None:
        """Compare body text case-insensitively using the original script.

        Raises:
            ValueError: Expected text is empty.
            AssertionError: The observed body lacks the expected text.
        """
        value = str(step.get("text") or "").strip()
        if not value:
            message = "expect_text requires text"
            raise ValueError(message)
        body = cast("JsonValue", await self.page.evaluate("() => document.body?.innerText || ''"))
        if value.lower() not in str(body or "").lower():
            message = f"text_missing: {value!r}"
            raise AssertionError(message)

    async def expect_title(self, step: JsonObject) -> None:
        """Retain text-before-value precedence and the case-insensitive title comparison.

        Raises:
            ValueError: Expected text and value are empty.
            AssertionError: The title lacks the expected text.
        """
        value = str(step.get("text") or step.get("value") or "").strip()
        if not value:
            message = "expect_title_contains requires text/value"
            raise ValueError(message)
        title = await self.page.title()
        if value.lower() not in str(title or "").lower():
            message = f"title_missing_substring: {value!r} not in {title!r}"
            raise AssertionError(message)

    async def expect_count(self, step: JsonObject) -> None:
        """Retain selector/count validation before querying the page.

        Raises:
            ValueError: A selector or integer count is missing.
            AssertionError: The locator count differs from the requested count.
        """
        selector = str(step.get("selector") or "").strip()
        if not selector:
            message = "expect_selector_count requires selector"
            raise ValueError(message)
        expected = 0
        with BrowserFailure() as conversion:
            expected = required_int(step.get("count"))
        if conversion.error is not None:
            message = "expect_selector_count requires integer count"
            raise ValueError(message) from conversion.error
        got = await self.page.locator(selector).count()
        if int(got) != int(expected):
            message = f"selector_count_mismatch: selector={selector!r} got={got} expected={expected}"
            raise AssertionError(message)

    async def set_viewport(self, step: JsonObject) -> None:
        """Convert width before height, then pass both to the native API.

        Raises:
            ValueError: A dimension is not integer-convertible.
        """
        width = height = 0
        with BrowserFailure() as conversion:
            width = required_int(step.get("width"))
            height = required_int(step.get("height"))
        if conversion.error is not None:
            message = "set_viewport requires width,height ints"
            raise ValueError(message) from conversion.error
        await self.page.set_viewport_size({"width": width, "height": height})

    async def screenshot(self, step: JsonObject) -> None:
        """Keep original filename filtering and optional screenshot behavior."""
        if self.artifacts.directory:
            name = str(step.get("name") or "screenshot").strip() or "screenshot"
            filtered = ""
            for char in name:
                if char.isalnum() or char in {"-", "_"}:
                    filtered += char
            safe = filtered[:60] or "screenshot"
            await self.artifacts.capture(self.page, f"{safe}.png", f"screenshot_{safe}")

    @staticmethod
    async def sleep(step: JsonObject) -> None:
        """Retain the 250ms fallback and nonnegative sleep duration."""
        milliseconds = coerce_int(step.get("ms"), default=250)
        await asyncio.sleep(max(0.0, milliseconds / 1000.0))
