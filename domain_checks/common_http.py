# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP execution boundary for domain checks."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

import httpx

from domain_checks.common_text import (
    find_forbidden_text,
    html_to_visible_text,
    safe_url,
)

if TYPE_CHECKING:
    from domain_checks.common_models import DomainCheckSpec
    from domain_checks.types import JsonObject

_DENIED_CAPTURE_HEADERS = {"authorization", "cookie", "set-cookie"}
_HEADER_NAME_RE = re.compile(r"[a-z0-9-]{1,80}")
_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX_EXCLUSIVE = 300


def _captured_headers(spec: DomainCheckSpec, response: httpx.Response) -> JsonObject:
    captured: JsonObject = {}
    for raw_name in spec.capture_headers[:30]:
        name = str(raw_name or "").strip()
        key = name.lower()
        if not name or key in _DENIED_CAPTURE_HEADERS:
            continue
        if _HEADER_NAME_RE.fullmatch(key) is None:
            continue
        value = cast(
            "str | None",
            response.headers.get(name) or response.headers.get(key),
        )
        if value is not None:
            captured[key] = value[:300]
    return captured


def _final_host_details(
    spec: DomainCheckSpec,
    response: httpx.Response,
) -> tuple[str, str, bool]:
    final_host = (urlsplit(str(response.url)).hostname or "").lower()
    expected_suffix = (spec.expected_final_host_suffix or "").strip().lower()
    final_host_ok = not expected_suffix or (bool(final_host) and final_host.endswith(expected_suffix))
    return final_host, expected_suffix, final_host_ok


def _status_ok(spec: DomainCheckSpec, status_code: int) -> bool:
    if spec.allowed_status_codes is not None:
        return status_code in spec.allowed_status_codes
    return _HTTP_SUCCESS_MIN <= status_code < _HTTP_SUCCESS_MAX_EXCLUSIVE


async def http_get_check(
    spec: DomainCheckSpec,
    client: httpx.AsyncClient,
) -> tuple[bool, JsonObject]:
    """Fetch a domain and evaluate its HTTP-level contract.

    Returns:
        The HTTP-contract result and its diagnostic details.
    """
    started = time.perf_counter()
    try:
        response = await client.get(
            spec.url,
            follow_redirects=True,
            timeout=spec.http_timeout_seconds,
        )
    except httpx.RequestError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return False, {
            "error": f"http_error: {type(exc).__name__}: {exc}",
            "http_elapsed_ms": round(elapsed_ms, 3),
        }

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    body_text = html_to_visible_text(response.text or "")
    forbidden_hits = find_forbidden_text(body_text, spec.forbidden_text_any)
    final_host, expected_suffix, final_host_ok = _final_host_details(spec, response)
    ok = _status_ok(spec, response.status_code) and not forbidden_hits and final_host_ok
    return ok, {
        "status_code": response.status_code,
        "final_url": safe_url(str(response.url)),
        "final_host": final_host,
        "expected_final_host_suffix": expected_suffix or None,
        "final_host_ok": final_host_ok,
        "forbidden_hits": forbidden_hits,
        "captured_headers": _captured_headers(spec, response),
        "http_elapsed_ms": round(elapsed_ms, 3),
    }
