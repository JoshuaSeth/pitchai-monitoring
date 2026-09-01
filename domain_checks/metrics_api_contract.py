# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run independently attributed API monitoring contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .api_contract_coordination import ApiContractCoordinator
from .api_contract_execution import capture_api_contract_check
from .api_contract_models import ApiContractCheckResult, ApiExecutionContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .api_contract_models import ApiConfig, ApiHttpClient, ApiValue

__all__ = ("ApiContractCheckResult", "run_api_contract_checks")

_DEFAULT_COORDINATOR = ApiContractCoordinator()


async def run_api_contract_checks(
    *,
    http_client: ApiHttpClient,
    domain: str,
    base_url: str,
    checks: Sequence[ApiValue],
    timeout_seconds: float = 10.0,
) -> list[ApiContractCheckResult]:
    """Run every valid configured API check in declaration order.

    Returns:
        Per-check results with failures isolated to the owning domain.
    """
    context = ApiExecutionContext(
        client=http_client,
        coordinator=_DEFAULT_COORDINATOR,
        domain=domain.strip().lower(),
        base_url=base_url.strip(),
        timeout_seconds=float(timeout_seconds),
    )
    return [
        await capture_api_contract_check(context, cast("ApiConfig", raw))
        for raw in checks
        if isinstance(raw, dict)
    ]
