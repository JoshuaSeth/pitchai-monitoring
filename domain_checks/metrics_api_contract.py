# Copyright (c) 2026 PitchAI. All rights reserved.
"""Sequential API contract observations with explicit configuration/error boundaries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .api_contract_observation import ApiObservation
from .api_contract_request import ApiCheck
from .api_contract_values import as_list as _as_list
from .api_contract_values import get_path as _get_path
from .api_contract_values import headers_with_env as _headers_with_env
from .synthetic_values import substitute_env_refs as _substitute_env_refs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from httpx import AsyncClient

    from .event_bus_delivery import JsonObject, JsonValue

__all__ = [
    "ApiContractCheckResult", "_as_list", "_get_path", "_headers_with_env", "_substitute_env_refs",
    "run_api_contract_checks",
]


@dataclass(frozen=True)
class _ApiCheckIdentity:
    """The original leading result fields identify a configured observation."""

    domain: str
    name: str
    ok: bool
    url: str


@dataclass(frozen=True)
class ApiContractCheckResult(_ApiCheckIdentity):
    """The existing ordered public result fields, including response and failure evidence."""

    status_code: int | None
    elapsed_ms: float | None
    error: str | None
    details: JsonObject


async def run_api_contract_checks(
    *,
    http_client: AsyncClient,
    domain: str,
    base_url: str,
    checks: Sequence[JsonValue],
    timeout_seconds: float = 10.0,
) -> list[ApiContractCheckResult]:
    """Normalize then observe each configured mapping in its original order.

    Returns:
        Original success/failure records. Configuration errors before observation
        and cancellation still propagate to the caller.
    """
    results: list[ApiContractCheckResult] = []
    cleaned_domain = str(domain or "").strip().lower()
    base = str(base_url or "").strip()
    for raw in checks:
        if not isinstance(raw, dict):
            continue
        check = ApiCheck.read(raw, base)
        observed = ApiObservation(time.perf_counter())
        await observed.run(http_client, check, timeout_seconds)
        results.append(ApiContractCheckResult(
            domain=cleaned_domain, name=check.name, ok=observed.ok, url=check.url,
            status_code=observed.status_code,
            elapsed_ms=round(float(observed.elapsed_ms), 3) if observed.elapsed_ms is not None else None,
            error=observed.error, details=observed.details,
        ))
    return results
