# Copyright (c) 2026 PitchAI. All rights reserved.
"""Execute API monitoring contracts with scoped resource coordination."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, cast

from .api_contract_configuration import build_api_contract_spec, fallback_api_identity
from .api_contract_models import ApiContractCheckResult

if TYPE_CHECKING:
    from .api_contract_models import (
        ApiConfig,
        ApiContractSpec,
        ApiDetails,
        ApiExecutionContext,
        ApiHttpResponse,
        ApiValue,
    )


def _path_value(value: ApiValue, path: str) -> tuple[bool, ApiValue | None]:
    current = value
    for segment in path.split("."):
        key = segment.strip()
        if not key:
            return False, None
        if isinstance(current, list):
            values = cast("list[ApiValue]", current)
            if not key.isdecimal() or int(key) >= len(values):
                return False, None
            current = values[int(key)]
        elif isinstance(current, dict):
            values_by_key = cast("dict[ApiValue, ApiValue]", current)
            if key not in values_by_key:
                return False, None
            current = values_by_key[key]
        else:
            return False, None
    return True, current


async def _decode_json(response: ApiHttpResponse) -> ApiValue:
    await asyncio.sleep(0)
    return response.json()


def _exception_text(error: BaseException, prefix: str | None = None) -> str:
    rendered = f"{type(error).__name__}: {error}"
    return rendered if prefix is None else f"{prefix}: {rendered}"


async def _json_failure(
    response: ApiHttpResponse,
    spec: ApiContractSpec,
    details: ApiDetails,
) -> str | None:
    if not spec.expectation.required_paths and not spec.expectation.equal_paths:
        return None
    outcome = (await asyncio.gather(_decode_json(response), return_exceptions=True))[0]
    if isinstance(outcome, asyncio.CancelledError):
        raise outcome
    if isinstance(outcome, BaseException):
        return _exception_text(outcome, "json_parse_error")
    missing = [path for path in spec.expectation.required_paths[:50] if not _path_value(outcome, path)[0]]
    if missing:
        details["missing_json_paths"] = missing[:25]
        return "missing_json_paths"
    mismatches: list[str] = []
    for path, expected in list(spec.expectation.equal_paths.items())[:50]:
        exists, observed = _path_value(outcome, path)
        if not exists:
            mismatches.append(f"{path}: missing")
        elif observed != expected:
            mismatches.append(f"{path}: got={observed!r} expected={expected!r}")
    if mismatches:
        details["json_mismatches"] = mismatches[:25]
        return "json_value_mismatch"
    return None


async def _response_failure(
    response: ApiHttpResponse,
    spec: ApiContractSpec,
    elapsed_ms: float,
    details: ApiDetails,
) -> str | None:
    status_code = int(response.status_code)
    if status_code not in spec.expectation.statuses:
        return f"unexpected_status: {status_code} not in {list(spec.expectation.statuses)}"
    content_type = response.headers.get("content-type") or ""
    expected_type = spec.expectation.content_type
    if expected_type and expected_type.lower() not in content_type.lower():
        return f"unexpected_content_type: {content_type.lower()!r} missing {expected_type!r}"
    json_failure = await _json_failure(response, spec, details)
    if json_failure is not None:
        return json_failure
    elapsed_limit = spec.expectation.max_elapsed_ms
    if elapsed_limit is not None and elapsed_ms > elapsed_limit:
        return f"slow_api: elapsed_ms={elapsed_ms:.1f} > {elapsed_limit:.1f}"
    return None


async def perform_api_contract_check(
    context: ApiExecutionContext,
    raw: ApiConfig,
) -> ApiContractCheckResult:
    """Run one normalized API check.

    Returns:
        The independently attributed check result.
    """
    spec = build_api_contract_spec(raw, context.base_url)
    wait_started = time.perf_counter()
    async with context.coordinator.request_slot(spec.coordination_key):
        request_started = time.perf_counter()
        response = await context.client.request(
            spec.request.method,
            spec.request.url,
            json=spec.request.json_body,
            content=spec.request.text_body.encode() if spec.request.text_body is not None else None,
            headers=spec.request.headers,
            timeout=context.timeout_seconds,
            follow_redirects=True,
        )
    elapsed_ms = (time.perf_counter() - request_started) * 1000.0
    details: ApiDetails = {
        "content_type": response.headers.get("content-type"),
        "final_url": str(response.url),
    }
    if spec.coordination_key is not None:
        details["coordination_wait_ms"] = round((request_started - wait_started) * 1000.0, 3)
    error = await _response_failure(response, spec, elapsed_ms, details)
    return ApiContractCheckResult(
        domain=context.domain,
        name=spec.name,
        ok=error is None,
        url=spec.request.url,
        status_code=int(response.status_code),
        elapsed_ms=round(elapsed_ms, 3),
        error=error,
        details=details,
        coordination_key=spec.coordination_key,
    )


async def capture_api_contract_check(
    context: ApiExecutionContext,
    raw: ApiConfig,
) -> ApiContractCheckResult:
    """Convert an edge failure into a secret-safe failed check result.

    Returns:
        A successful result or a failed result describing the edge exception.
    """
    started = time.perf_counter()
    outcome = (await asyncio.gather(perform_api_contract_check(context, raw), return_exceptions=True))[0]
    if isinstance(outcome, asyncio.CancelledError):
        raise outcome
    if not isinstance(outcome, BaseException):
        return outcome
    name, url = fallback_api_identity(raw, context.base_url)
    return ApiContractCheckResult(
        domain=context.domain,
        name=name,
        ok=False,
        url=url,
        status_code=None,
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
        error=_exception_text(outcome),
        details={},
    )
