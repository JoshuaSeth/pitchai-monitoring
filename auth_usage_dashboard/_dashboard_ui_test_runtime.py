# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed Playwright and Chromium boundary for the legacy dashboard UI test."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType
    from typing import TypedDict

    from .timeseries_types import JsonValue

    class Viewport(TypedDict):
        """Browser viewport size in CSS pixels."""

        width: int
        height: int

    class BoundingBox(TypedDict):
        """Rendered element geometry in CSS pixels."""

        x: float
        y: float
        width: float
        height: float


class ElementQuery(Protocol):
    """Navigation from one lazy element query to narrower queries."""

    @property
    def first(self) -> Locator:
        """Return the first matching element."""
        raise NotImplementedError

    def nth(self, index: int) -> Locator:
        """Return the matching element at one zero-based position."""
        raise NotImplementedError

    def locator(self, selector: str) -> Locator:
        """Return the descendants matching one selector."""
        raise NotImplementedError


class ElementReader(Protocol):
    """Read-only inspection of the elements behind one query."""

    async def wait_for(self) -> None:
        """Wait until the element is attached and visible."""
        raise NotImplementedError

    async def count(self) -> int:
        """Return the number of matching elements."""
        raise NotImplementedError

    async def inner_text(self) -> str:
        """Return the rendered text of the element."""
        raise NotImplementedError

    async def get_attribute(self, name: str) -> str | None:
        """Return one attribute value, if present."""
        raise NotImplementedError


class ElementLayout(Protocol):
    """Rendered visibility and geometry of one element."""

    async def bounding_box(self) -> BoundingBox | None:
        """Return the rendered geometry, if the element is visible."""
        raise NotImplementedError

    async def is_hidden(self) -> bool:
        """Return whether the element is hidden."""
        raise NotImplementedError


class ElementControl(Protocol):
    """User interactions with one element."""

    async def click(self) -> None:
        """Click the element."""
        raise NotImplementedError

    async def select_option(self, value: str) -> list[str]:
        """Select one option of a select element by value."""
        raise NotImplementedError


class Locator(ElementQuery, ElementReader, ElementLayout, ElementControl, Protocol):
    """Lazy element query used by the dashboard UI assertions."""


class NavigationResponse(Protocol):
    """Main-document response returned by a page navigation."""

    @property
    def status(self) -> int:
        """Return the HTTP status code."""
        raise NotImplementedError

    @property
    def ok(self) -> bool:
        """Return whether the status is successful."""
        raise NotImplementedError


class Page(Protocol):
    """One browser tab rendering the dashboard."""

    async def goto(self, url: str, *, wait_until: str) -> NavigationResponse | None:
        """Navigate the tab and return the main-document response."""
        raise NotImplementedError

    def locator(self, selector: str, *, has_text: str | None = None) -> Locator:
        """Return the elements matching one selector and optional text."""
        raise NotImplementedError

    async def evaluate(self, expression: str) -> JsonValue:
        """Evaluate one JavaScript function and return its JSON result."""
        raise NotImplementedError


class Browser(Protocol):
    """One launched headless browser."""

    async def new_page(self, *, viewport: Viewport) -> Page:
        """Open one tab with a fixed viewport."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the browser and every tab."""
        raise NotImplementedError


class BrowserType(Protocol):
    """Launcher for one browser engine."""

    @property
    def name(self) -> str:
        """Return the browser engine name."""
        raise NotImplementedError

    async def launch(self, *, headless: bool, executable_path: str, args: list[str]) -> Browser:
        """Launch one browser executable."""
        raise NotImplementedError


class PlaywrightDriver(Protocol):
    """Running Playwright driver."""

    @property
    def chromium(self) -> BrowserType:
        """Return the Chromium launcher."""
        raise NotImplementedError

    async def stop(self) -> None:
        """Stop the driver."""
        raise NotImplementedError


class PlaywrightSession(Protocol):
    """Async context that starts and stops the Playwright driver."""

    async def __aenter__(self) -> PlaywrightDriver:
        """Start the driver."""
        raise NotImplementedError

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Stop the driver."""
        raise NotImplementedError


_PLAYWRIGHT_MODULE = cast("dict[str, object]", vars(import_module("playwright.async_api")))
_COMMON_CHECK_MODULE = cast("dict[str, object]", vars(import_module("domain_checks.common_check")))
ASYNC_PLAYWRIGHT = cast("Callable[[], PlaywrightSession]", _PLAYWRIGHT_MODULE["async_playwright"])
FIND_CHROMIUM = cast("Callable[[], str | None]", _COMMON_CHECK_MODULE["find_chromium_executable"])
