# Copyright (c) 2026 PitchAI. All rights reserved.
"""Authenticated API routes for first-class client hotpath signals."""

from __future__ import annotations

import asyncio
import hmac
import time
from typing import TYPE_CHECKING, cast

from . import hotpath_web_runtime as web_runtime
from .hotpath_config import load_hotpath_config
from .hotpath_store_read import build_hotpath_snapshot
from .hotpath_store_write import ingest_report
from .hotpath_types import (
    HotpathContractError,
    HotpathReportRequest,
    load_inventory,
    validate_report_identity,
)

if TYPE_CHECKING:
    from dataclasses import dataclass

    from .hotpath_config import HotpathRuntimeConfig
    from .settings import RegistrySettings

    @dataclass(frozen=True)
    class _RegistryState:
        settings: RegistrySettings

    @dataclass(frozen=True)
    class _RegistryApplication:
        state: _RegistryState

_MAX_FUTURE_SKEW_SECONDS = 300.0
_AUTH_PART_COUNT = 2
_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254
type HotpathApiValue = (
    str | int | float | bool | list[HotpathApiValue] | dict[str, HotpathApiValue] | None
)
router = web_runtime.router


@router.post("/api/v1/hotpaths/reports")
async def report_hotpath(
    report: HotpathReportRequest,
    request: web_runtime.Request,
) -> dict[str, HotpathApiValue]:
    """Accept one canonical manual or reminder-driven report.

    Returns:
        A deterministic receipt and duplicate marker.

    Raises:
        HTTPException: If authentication, time, or lane identity is invalid.
    """
    config = _runtime_config(request)
    _require_reporter(request, config)
    report = HotpathReportRequest.model_validate(report)
    now_ts = time.time()
    if report.occurred_at.timestamp() > now_ts + _MAX_FUTURE_SKEW_SECONDS:
        raise web_runtime.HTTPException(
            status_code=422,
            detail="occurred_at exceeds the allowed clock skew",
        )
    try:
        inventory = load_inventory(config.inventory_path)
    except (HotpathContractError, OSError) as error:
        raise web_runtime.HTTPException(
            status_code=503,
            detail="hotpath_inventory_unavailable",
        ) from error
    try:
        lane = validate_report_identity(report, inventory)
    except HotpathContractError as error:
        raise web_runtime.HTTPException(status_code=422, detail=str(error)) from error
    ingested = await asyncio.to_thread(
        ingest_report,
        config.db_path,
        inventory,
        report,
        lane,
        received_at_ts=now_ts,
    )
    return {"duplicate": ingested.duplicate, "ok": True, "receipt": ingested.receipt}


@router.get("/dashboard/api/v1/hotpaths/summary")
@router.get("/api/v1/hotpaths/summary")
async def hotpath_summary(request: web_runtime.Request) -> dict[str, HotpathApiValue]:
    """Return the machine-readable first-class hotpath signal summary.

    Returns:
        The complete current hotpath projection.

    Raises:
        HTTPException: If reader authentication or inventory loading fails.
    """
    config = _runtime_config(request)
    _require_reader(request, config)
    try:
        inventory = load_inventory(config.inventory_path)
    except (HotpathContractError, OSError) as error:
        raise web_runtime.HTTPException(
            status_code=503,
            detail="hotpath_inventory_unavailable",
        ) from error
    snapshot = await asyncio.to_thread(
        build_hotpath_snapshot,
        config.db_path,
        inventory,
        now_ts=time.time(),
    )
    return {"hotpaths": snapshot, "ok": True}


def _runtime_config(request: web_runtime.Request) -> HotpathRuntimeConfig:
    application = cast("_RegistryApplication", cast("object", request.app))
    return load_hotpath_config(application.state.settings)


def _require_reporter(
    request: web_runtime.Request,
    config: HotpathRuntimeConfig,
) -> None:
    provided = _bearer_token(request)
    if not provided:
        raise web_runtime.HTTPException(status_code=401, detail="missing_bearer_token")
    if not config.reporter_token:
        raise web_runtime.HTTPException(
            status_code=503,
            detail="hotpath_reporter_token_not_configured",
        )
    if not hmac.compare_digest(provided, config.reporter_token):
        raise web_runtime.HTTPException(status_code=403, detail="invalid_token")


def _require_reader(
    request: web_runtime.Request,
    config: HotpathRuntimeConfig,
) -> None:
    provided = _bearer_token(request)
    bearer_valid = bool(provided) and any(
        hmac.compare_digest(provided, token) for token in config.reader_tokens
    )
    identity = request.headers.get(config.dashboard_identity_header, "")
    if bearer_valid or _valid_identity(identity):
        return
    status_code = 401 if not provided and not identity else 403
    raise web_runtime.HTTPException(
        status_code=status_code,
        detail="hotpath_reader_authentication_required",
    )


def _valid_identity(raw: str) -> bool:
    if raw != raw.strip() or len(raw) > _MAX_EMAIL_LENGTH:
        return False
    email = raw.casefold()
    local_part, separator, domain = email.rpartition("@")
    return (
        email.count("@") == 1
        and separator == "@"
        and bool(local_part)
        and domain == _ALLOWED_IDENTITY_DOMAIN
    )


def _bearer_token(request: web_runtime.Request) -> str:
    raw = request.headers.get("authorization", "")
    parts = raw.split(None, 1)
    if len(parts) != _AUTH_PART_COUNT or parts[0].casefold() != "bearer":
        return ""
    return parts[1].strip()
