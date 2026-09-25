# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP execution for API contract checks."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, NamedTuple

import httpx

from domain_checks.api_contract_assertions import evaluate_api_response
from domain_checks.api_contract_config import parse_api_check
from domain_checks.api_contract_models import ApiContractCheckResult
from domain_checks.common_env import substitute_env_refs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from domain_checks.api_contract_models import ApiCheckSpec
    from domain_checks.types import JsonObject


class _ApiExecution(NamedTuple):
    elapsed_ms: float
    error: str | None
    details: JsonObject
    status_code: int


def _request_headers(spec: ApiCheckSpec) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in spec.headers.items():
        headers[str(key)] = substitute_env_refs(str(value))
    return headers


async def _request_and_evaluate(
    http_client: httpx.AsyncClient,
    spec: ApiCheckSpec,
    timeout_seconds: float,
    started: float,
) -> _ApiExecution:
    response = await http_client.request(
        spec.method,
        spec.url,
        json=spec.request_json,
        content=(spec.request_data.encode("utf-8") if spec.request_data is not None else None),
        headers=_request_headers(spec),
        timeout=float(timeout_seconds),
        follow_redirects=True,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    error, details = evaluate_api_response(spec, response, elapsed_ms)
    return _ApiExecution(elapsed_ms, error, details, int(response.status_code))


async def _execute_api_check(
    http_client: httpx.AsyncClient,
    domain: str,
    spec: ApiCheckSpec,
    timeout_seconds: float,
) -> ApiContractCheckResult:
    started = time.perf_counter()
    try:
        execution = await _request_and_evaluate(
            http_client,
            spec,
            timeout_seconds,
            started,
        )
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        error = f"{type(exc).__name__}: {exc}"
        details = {}
        status_code = None
    else:
        elapsed_ms = execution.elapsed_ms
        error = execution.error
        details = execution.details
        status_code = execution.status_code
    return ApiContractCheckResult(
        domain=domain,
        name=spec.name,
        ok=error is None,
        url=spec.url,
        status_code=status_code,
        elapsed_ms=round(elapsed_ms, 3),
        error=error,
        details=details,
    )


async def run_api_contract_checks(
    *,
    http_client: httpx.AsyncClient,
    domain: str,
    base_url: str,
    checks: Sequence[JsonObject],
    timeout_seconds: float = 10.0,
) -> list[ApiContractCheckResult]:
    """Parse and execute configured API contract checks in order.

    Returns:
        API contract outcomes in configuration order.
    """
    cleaned_domain = str(domain or "").strip().lower()
    cleaned_base_url = str(base_url or "").strip()
    results: list[ApiContractCheckResult] = []
    for raw_check in checks:
        spec = parse_api_check(raw_check, cleaned_base_url)
        results.append(
            await _execute_api_check(
                http_client,
                cleaned_domain,
                spec,
                timeout_seconds,
            ),
        )
    return results
