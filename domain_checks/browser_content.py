# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing browser response, text and selector product predicates."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .browser_selectors import any_selector, missing_selectors
from .check_text import forbidden_hits, host_expectation, normalize_text, safe_url, status_allowed

if TYPE_CHECKING:
    from playwright.async_api import Page, Response

    from .common_check import DomainCheckSpec
    from .event_bus_delivery import JsonObject


async def observe_content(
    spec: DomainCheckSpec, page: Page, response: Response | None, timeout_ms: int,
) -> tuple[bool, JsonObject]:
    """Read title and body before all/any selector waits, retaining observation order.

    Returns:
        The same product predicates and detail values; timing belongs to the caller.
    """
    status = response.status if response else None
    title = await page.title()
    title_ok = True
    if spec.expected_title_contains:
        title_ok = spec.expected_title_contains.lower() in (title or "").lower()
    host = host_expectation(page.url, spec.expected_final_host_suffix)
    body = normalize_text(cast("str", await page.evaluate("() => document.body?.innerText || ''")))
    hits = forbidden_hits(spec.forbidden_text_any, body)
    missing_all = await missing_selectors(page, spec.required_selectors_all, timeout_ms)
    candidates = [check.selector for check in spec.required_selectors_any]
    any_ok = await any_selector(page, spec.required_selectors_any, timeout_ms)
    missing_text = [text for text in spec.required_text_all if normalize_text(text) not in body]
    ok = (status_allowed(status, spec.allowed_status_codes) and title_ok and host.ok
          and not hits and not missing_all and any_ok and not missing_text)
    return ok, {
        "final_url": safe_url(page.url), "final_host": host.hostname,
        "expected_final_host_suffix": host.suffix or None, "final_host_ok": host.ok,
        "http_status": status, "title": title, "title_ok": title_ok,
        "forbidden_hits": list(hits), "missing_selectors_all": list(missing_all),
        "required_any_selectors": list(candidates), "required_any_ok": any_ok, "missing_text": list(missing_text),
    }
