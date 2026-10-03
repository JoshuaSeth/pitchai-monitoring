# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing HTTP observation and bounded response-header capture."""

from __future__ import annotations

import re
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

import httpx

from .check_text import forbidden_hits, host_expectation, html_to_visible_text, safe_url, status_allowed

if TYPE_CHECKING:
    from types import TracebackType

    from .common_check import DomainCheckSpec
    from .event_bus_delivery import JsonObject


def captured_headers(response: httpx.Response, names: list[str]) -> dict[str, str]:
    """Capture at most the first 30 configured names, preserving sensitive-name denial.

    Returns:
        Lowercase names with the original 300-character value bound.
    """
    result: dict[str, str] = {}
    deny = {"authorization", "cookie", "set-cookie"}
    for raw_name in names[:30]:
        name = str(raw_name or "").strip()
        key = name.lower()
        if not name or key in deny or not re.fullmatch(r"[a-z0-9-]{1,80}", key):
            continue
        value = None
        with suppress(Exception):
            value = cast("str | None", response.headers.get(name) or response.headers.get(key))
        if value is not None:
            result[key] = str(value)[:300]
    return result


@dataclass
class _RequestFailure:
    """Capture only HTTPX request failures, leaving other errors and cancellation intact."""

    error: httpx.RequestError | None = None

    def __enter__(self) -> Self:
        """Return this single request boundary before performing HTTP IO."""
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _trace: TracebackType | None) -> bool:
        """Return true only for the original HTTPX request-error contract."""
        if not isinstance(error, httpx.RequestError):
            return False
        self.error = error
        return True


async def http_get_check(spec: DomainCheckSpec, client: httpx.AsyncClient) -> tuple[bool, JsonObject]:
    """Follow redirects and preserve request-error versus content-failure observations.

    Returns:
        Product success plus the existing JSON detail keys and elapsed timing.
    """
    started = time.perf_counter()
    response = None
    with _RequestFailure() as failure:
        response = await client.get(spec.url, follow_redirects=True, timeout=spec.http_timeout_seconds)
    if failure.error is not None:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return False, {
            "error": f"http_error: {type(failure.error).__name__}: {failure.error}",
            "http_elapsed_ms": round(elapsed_ms, 3),
        }
    response = cast("httpx.Response", response)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    body = response.text or ""
    hits = forbidden_hits(spec.forbidden_text_any, html_to_visible_text(body))
    headers = captured_headers(response, spec.capture_headers)
    host = host_expectation(str(response.url), spec.expected_final_host_suffix)
    ok = status_allowed(response.status_code, spec.allowed_status_codes) and not hits and host.ok
    return ok, {
        "status_code": response.status_code, "final_url": safe_url(str(response.url)),
        "final_host": host.hostname, "expected_final_host_suffix": host.suffix or None,
        "final_host_ok": host.ok, "forbidden_hits": list(hits),
        "captured_headers": dict(headers), "http_elapsed_ms": round(elapsed_ms, 3),
    }
