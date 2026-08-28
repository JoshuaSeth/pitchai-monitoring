# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for browser proof runtime objects."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast, overload

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from types import TracebackType
    from typing import Literal

    from .json_types import JsonValue


class ConsoleMessage(Protocol):
    """Browser console message fields retained by proof receipts."""

    @property
    def type(self) -> str:
        """Return the console severity."""
        raise NotImplementedError

    @property
    def text(self) -> str:
        """Return the console message text."""
        raise NotImplementedError


class BrowserRequest(Protocol):
    """Browser request fields retained by proof receipts."""

    @property
    def url(self) -> str:
        """Return the request URL."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Route(Protocol):
    """Intercepted browser route surface."""

    @property
    def request(self) -> BrowserRequest:
        """Return the intercepted request."""
        raise NotImplementedError

    async def fulfill(self, *, json: JsonValue) -> None:
        """Fulfil the route with deterministic JSON."""
        raise NotImplementedError


class Locator(Protocol):
    """Locator operations used by dashboard proof."""

    @property
    def first(self) -> Locator:
        """Return the first matching locator."""
        raise NotImplementedError

    async def inner_text(self) -> str:
        """Return rendered text."""
        raise NotImplementedError

    async def count(self) -> int:
        """Return the number of matching elements."""
        raise NotImplementedError

    async def click(self) -> None:
        """Click the located element."""
        raise NotImplementedError

    async def get_attribute(self, name: str) -> str | None:
        """Return one element attribute."""
        raise NotImplementedError

    def locator(self, selector: str) -> Locator:
        """Return a descendant locator."""
        raise NotImplementedError

    async def focus(self) -> None:
        """Focus the located element."""
        raise NotImplementedError

    async def fill(self, value: str) -> None:
        """Fill the located field."""
        raise NotImplementedError


class Keyboard(Protocol):
    """Keyboard operation used by accessible tab proof."""

    async def press(self, key: str) -> None:
        """Press one keyboard key."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Page(Protocol):
    """Browser page surface used by dashboard proof."""

    @property
    def keyboard(self) -> Keyboard:
        """Return the page keyboard."""
        raise NotImplementedError

    def locator(self, selector: str) -> Locator:
        """Create one page locator."""
        raise NotImplementedError

    async def goto(self, url: str) -> None:
        """Navigate to one URL."""
        raise NotImplementedError

    async def wait_for_function(self, expression: str) -> None:
        """Wait for one browser-side predicate."""
        raise NotImplementedError

    async def set_viewport_size(self, viewport: Mapping[str, int]) -> None:
        """Set the viewport size."""
        raise NotImplementedError

    async def evaluate(self, expression: str) -> JsonValue:
        """Evaluate one browser-side expression."""
        raise NotImplementedError

    async def screenshot(self, *, path: str, full_page: bool) -> None:
        """Capture the rendered page as a browser proof artifact."""
        raise NotImplementedError

    @overload
    def on(self, event: Literal["console"], callback: Callable[[ConsoleMessage], None]) -> None:
        ...

    @overload
    def on(self, event: Literal["pageerror"], callback: Callable[[Exception], None]) -> None:
        ...

    @overload
    def on(self, event: Literal["requestfailed"], callback: Callable[[BrowserRequest], None]) -> None:
        ...

    async def route(
        self,
        pattern: str,
        handler: Callable[[Route], Awaitable[None]],
    ) -> None:
        """Register one deterministic request handler."""
        raise NotImplementedError


class BrowserContext(Protocol):
    """Isolated browser context used by proof."""

    async def new_page(self) -> Page:
        """Create one browser page."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the browser context."""
        raise NotImplementedError


class Browser(Protocol):
    """Browser process surface used by proof and legacy checks."""

    async def new_context(self, *, extra_http_headers: Mapping[str, str]) -> BrowserContext:
        """Create one isolated browser context."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the browser process."""
        raise NotImplementedError


class Chromium(Protocol):
    """Chromium launcher used by browser proof."""

    async def launch(
        self,
        *,
        headless: bool,
        executable_path: str,
        args: list[str],
    ) -> Browser:
        """Launch one bounded browser process."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Playwright(Protocol):
    """Playwright engine surface used by browser proof."""

    @property
    def chromium(self) -> Chromium:
        """Return the Chromium launcher."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class PlaywrightContext(Protocol):
    """Asynchronous Playwright lifetime context."""

    async def __aenter__(self) -> Playwright:
        """Start the browser automation runtime."""
        raise NotImplementedError

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Stop the browser automation runtime."""
        raise NotImplementedError


class AsyncPlaywrightFactory(Protocol):
    """Factory for the Playwright lifetime context."""

    def __call__(self) -> PlaywrightContext:
        """Return one asynchronous Playwright context."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _PlaywrightModule(NamedTuple):
    async_playwright: object


_PLAYWRIGHT = cast("_PlaywrightModule", cast("object", import_module("playwright.async_api")))
async_playwright = cast("AsyncPlaywrightFactory", _PLAYWRIGHT.async_playwright)
