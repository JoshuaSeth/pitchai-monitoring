# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant run/artifact reads and the existing credential-scoped status summary."""

from __future__ import annotations

import asyncio
import hmac
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import fastapi
from fastapi.responses import FileResponse

from . import auth as registry_auth
from . import db as dbm
from .app_context import RegistryContext
from .dashboard_records import array_or_empty, integer, required_object

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record

router = fastapi.APIRouter()


def _artifact_path(directory: str, tenant_id: str, test_id: str, run_id: str, name: str) -> Path:
    base = Path(directory).resolve()
    file_path = (base / tenant_id / test_id / run_id / name).resolve()
    if base not in file_path.parents:
        raise fastapi.HTTPException(status_code=400, detail="invalid_artifact_path")
    if not file_path.exists() or not file_path.is_file():
        raise fastapi.HTTPException(status_code=404, detail="artifact_not_found")
    return file_path


@router.get("/api/v1/tests/{test_id}/runs", response_model=dict)
async def api_list_runs(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)], limit: int = 50,
) -> Record:
    """List runs within the authenticated tenant and requested test.

    Returns:
        The existing success envelope and ordered database rows.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    runs = cast("list[ConfigValue]", await asyncio.to_thread(
        dbm.list_runs, context.settings, tenant_id=auth.tenant_id, test_id=test_id, limit=limit,
    ))
    return {"ok": True, "runs": runs}


@router.get("/api/v1/runs/{run_id}", response_model=dict)
async def api_get_run(
    request: fastapi.Request, run_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
) -> Record:
    """Read one run through the original tenant-scoped database query.

    Returns:
        The existing run envelope.

    Raises:
        HTTPException: The database returned no run.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    run = cast("Record | None", await asyncio.to_thread(
        dbm.get_run, context.settings, tenant_id=auth.tenant_id, run_id=run_id,
    ))
    if not run:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "run": run}


@router.get("/api/v1/runs/{run_id}/artifacts/{name}", response_model=None)
async def api_get_artifact(
    request: fastapi.Request, run_id: str, name: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
) -> FileResponse:
    """Resolve the existing artifact path only after the tenant run lookup.

    Returns:
        A file response for the requested retained artifact.

    Raises:
        HTTPException: The run, test or file is missing, or its resolved path escapes.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    run = cast("Record | None", await asyncio.to_thread(
        dbm.get_run, context.settings, tenant_id=auth.tenant_id, run_id=run_id,
    ))
    if not run:
        raise fastapi.HTTPException(status_code=404, detail="run_not_found")
    tenant_id = auth.tenant_id
    test_id = str(run.get("test_id") or "").strip()
    if not test_id:
        raise fastapi.HTTPException(status_code=404, detail="test_not_found")
    file_path = _artifact_path(context.settings.artifacts_dir, tenant_id, test_id, run_id, name)
    return FileResponse(str(file_path))


@router.get("/api/v1/status/summary", response_model=dict)
async def api_status_summary(req: fastapi.Request) -> Record:
    """Return global status for admin/monitor credentials, otherwise tenant status.

    Returns:
        The original global record or filtered tenant success envelope.

    Raises:
        HTTPException: Tenant authentication did not authorize the request.
    """
    token = (req.headers.get("authorization") or "").strip()
    settings = RegistryContext(cast("fastapi.FastAPI", req.app)).settings
    if token.lower().startswith("bearer "):
        provided = token.split(None, 1)[1].strip()
        if settings.admin_token and hmac.compare_digest(provided, settings.admin_token.strip()):
            return cast("Record", await asyncio.to_thread(dbm.status_summary, settings))
        if settings.monitor_token and hmac.compare_digest(provided, settings.monitor_token.strip()):
            return cast("Record", await asyncio.to_thread(dbm.status_summary, settings))
    try:
        authenticated = registry_auth.require_tenant_auth(req, settings)
    except fastapi.HTTPException as exc:
        raise fastapi.HTTPException(status_code=401, detail="unauthorized") from exc
    summary = cast("Record", await asyncio.to_thread(dbm.status_summary, settings))
    tests: list[ConfigValue] = []
    failing: list[Record] = []
    for row in array_or_empty(summary.get("tests")):
        test = required_object(row)
        if str(test.get("tenant_id") or "") == authenticated.tenant_id:
            tests.append(test)
    for row in tests:
        test = required_object(row)
        effective = test.get("effective_ok")
        converted = 1
        # Preserve the existing summary's display-only malformed-value default.
        with suppress(Exception):
            converted = 1 if effective is None else integer(effective)
        if converted == 0:
            failing.append(test)
    return {"ok": True, "total_tests": len(tests), "failing_tests": len(failing), "tests": tests}
