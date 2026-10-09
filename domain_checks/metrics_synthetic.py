# Copyright (c) 2026 PitchAI. All rights reserved.
"""Sequential synthetic browser transactions with explicit resource/error ownership."""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, TypedDict, Unpack

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .browser_check import route_filter
from .browser_errors import is_browser_infra_error
from .browser_failure import BrowserFailure
from .synthetic_artifacts import SyntheticArtifacts
from .synthetic_steps import SyntheticSteps
from .synthetic_values import safe_str

if TYPE_CHECKING:
    from collections.abc import Sequence

    from playwright.async_api import Browser, BrowserContext, Page

    from .event_bus_delivery import JsonObject, JsonValue


@dataclass(frozen=True)
class SyntheticTransactionResult:
    """The unchanged public result fields for one attempted transaction."""

    domain: str
    name: str
    ok: bool
    elapsed_ms: float | None
    error: str | None
    details: JsonObject
    browser_infra_error: bool


@dataclass(frozen=True)
class SyntheticRequest:
    """Normalized shared inputs, computed before any transaction timing begins."""

    domain: str
    base: str
    timeout_ms: int
    trace_on_failure: bool

    @classmethod
    def from_options(cls, domain: str, base_url: str, options: SyntheticOptions) -> Self:
        """Preserve the existing keyword set and normalization order before browser IO.

        Returns:
            The original shared input values with native conversion failures retained.

        Raises:
            TypeError: An unexpected keyword is supplied.
        """
        unexpected = options.keys() - {"timeout_seconds", "artifacts_dir", "trace_on_failure"}
        if unexpected:
            first = next(key for key in options if key in unexpected)
            message = f"run_synthetic_transactions() got an unexpected keyword argument '{first}'"
            raise TypeError(message)
        return cls(str(domain or "").strip().lower(), str(base_url or "").strip(),
                   int(max(1.0, float(options.get("timeout_seconds", 35.0))) * 1000),
                   options.get("trace_on_failure", False))


@dataclass(frozen=True)
class SyntheticTransaction:
    """The original normalized name and retained nonempty step list."""

    name: str
    steps: list[JsonValue]


@dataclass
class SyntheticSession:
    """Own admitted resources and artifacts for exactly one transaction."""

    started: float
    artifacts: SyntheticArtifacts
    context: BrowserContext | None = None
    page: Page | None = None

    async def run(self, browser: Browser, request: SyntheticRequest,
                  transaction: SyntheticTransaction) -> SyntheticTransactionResult:
        """Execute a transaction and classify only ordinary browser/API failures.

        Returns:
            The original transaction result, before the caller releases resources.
        """
        with BrowserFailure() as failure:
            self.context = await browser.new_context(viewport={"width": 1280, "height": 720})
            with suppress(Exception):
                await self.context.route("**/*", route_filter)
            self.page = await self.context.new_page()
            await self.artifacts.start(self.context, enabled=request.trace_on_failure)
            actions = SyntheticSteps(self.page, request.base, request.timeout_ms, self.artifacts)
            for step in transaction.steps[:60]:
                await actions.run(step)
            elapsed_ms = (time.perf_counter() - self.started) * 1000.0
            result = SyntheticTransactionResult(domain=request.domain, name=transaction.name, ok=True,
                elapsed_ms=round(elapsed_ms, 3), error=None,
                details={"final_url": safe_str(self.page.url) if self.page else None, **self.artifacts.names},
                browser_infra_error=False)
            await self.artifacts.finish(self.context)
            return result
        return await self.failed(request.domain, transaction.name, failure)

    async def failed(self, domain: str, name: str, failure: BrowserFailure) -> SyntheticTransactionResult:
        """Preserve classification, clock, title and artifact ordering for failures.

        Returns:
            The same failure shape, including title only for Playwright failures.

        Raises:
            RuntimeError: The ordinary-error boundary did not retain an exception.
        """
        error = failure.error
        if error is None:
            message = "Synthetic failure boundary returned without an exception"
            raise RuntimeError(message)
        infrastructure = is_browser_infra_error(error)
        elapsed_ms = (time.perf_counter() - self.started) * 1000.0
        title = None
        has_title = isinstance(error, PlaywrightError)
        if has_title and self.page is not None:
            with suppress(Exception):
                title = await self.page.title()
        await self.artifacts.failure(self.page, self.context)
        kind = "TimeoutError" if isinstance(error, PlaywrightTimeoutError) else type(error).__name__
        error_text = f"{kind}: {error}"
        if self.artifacts.directory:
            fields: JsonObject = {"error": error_text,
                "final_url": safe_str(self.page.url) if self.page else None,
                "browser_infra_error": bool(infrastructure)}
            if has_title:
                fields["title"] = safe_str(title) if title else None
            self.artifacts.write_failure(fields)
        details: JsonObject = {"final_url": safe_str(self.page.url) if self.page else None}
        if has_title:
            details["title"] = safe_str(title) if title is not None else None
        details.update(self.artifacts.names)
        return SyntheticTransactionResult(domain=domain, name=name, ok=False,
            elapsed_ms=round(elapsed_ms, 3), error=error_text, details=details, browser_infra_error=infrastructure)

    async def close(self) -> None:
        """Close page then context, retaining cancellation and fatal cleanup errors."""
        if self.page is not None:
            with suppress(Exception):
                await self.page.close()
        if self.context is not None:
            with suppress(Exception):
                await self.context.close()


class SyntheticOptions(TypedDict, total=False):
    """The existing optional public transaction keywords and their concrete types."""

    timeout_seconds: float
    artifacts_dir: str | None
    trace_on_failure: bool


async def run_synthetic_transactions(
    *,
    domain: str,
    base_url: str,
    browser: Browser,
    transactions: Sequence[JsonValue],
    **options: Unpack[SyntheticOptions],
) -> list[SyntheticTransactionResult]:
    """Run configured transactions sequentially, keeping the original skip and step limits.

    Returns:
        One result for each transaction with a nonempty list of steps.

    """
    artifacts_dir = options.get("artifacts_dir")
    results: list[SyntheticTransactionResult] = []
    request = SyntheticRequest.from_options(domain, base_url, options)
    for value in transactions:
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "transaction").strip()[:120]
        steps = value.get("steps") or []
        if not isinstance(steps, list) or not steps:
            continue
        transaction = SyntheticTransaction(name, steps)
        session = SyntheticSession(time.perf_counter(), SyntheticArtifacts(artifacts_dir))
        try:
            results.append(await session.run(browser, request, transaction))
        finally:
            await session.close()
    return results
