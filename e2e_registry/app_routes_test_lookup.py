# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared tenant-owned test lookup for registry routes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import HTTPException

from e2e_registry import db as dbm

if TYPE_CHECKING:
    from e2e_registry.app_context import RegistryAppContext
    from e2e_registry.models import DatabaseRecord


async def require_tenant_test(
    context: RegistryAppContext,
    *,
    tenant_id: str,
    test_id: str,
) -> DatabaseRecord:
    """Return one tenant-owned test or raise the route-level not-found error.

    Returns:
        The requested persisted test record.

    Raises:
        HTTPException: If the tenant has no matching test.
    """
    test = await asyncio.to_thread(
        dbm.get_test,
        context.settings,
        tenant_id=tenant_id,
        test_id=test_id,
    )
    if test is None:
        raise HTTPException(status_code=404, detail="not_found")
    return test
