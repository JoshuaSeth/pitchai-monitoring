# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing monitoring HTTP routes with typed calculation and cache boundaries."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Annotated, cast

import fastapi

from . import db as dbm
from . import monitor_dashboard as md
from .app_dashboard_window import filter_summary_window

if TYPE_CHECKING:
    from .app_access import RegistryAccess
    from .app_context import RegistryContext
    from .dashboard_records import Record


def _series_bounds(
    now_ts: float, range_label: str, since_ts: float | None, until_ts: float | None,
) -> tuple[float, float]:
    if since_ts is None or until_ts is None:
        start, end = md.resolve_range(now_ts=now_ts, range_label=range_label)
        since_ts = float(start) if since_ts is None else float(since_ts)
        until_ts = float(end) if until_ts is None else float(until_ts)
    if float(until_ts) < float(since_ts):
        raise fastapi.HTTPException(status_code=400, detail="invalid_range")
    return float(since_ts), float(until_ts)


def install_monitoring_routes(context: RegistryContext, access: RegistryAccess) -> None:
    """Register the same six routes in their original order and access domains.

    The explicit dictionary response model retains the existing unrestricted
    mapping wire schema while internal calculations use typed retained values.
    Request annotations resolve through the runtime FastAPI module.
    """
    app = context.app

    async def api_monitoring_summary(
        req: fastapi.Request, range_label: Annotated[str, fastapi.Query(alias="range")] = "24h",
    ) -> Record:
        access.require_monitoring_access(req)
        settings = context.settings
        now_ts = time.time()
        since_ts, until_ts = md.resolve_range(now_ts=now_ts, range_label=range_label)
        data = await context.monitor_data()
        e2e_status = cast("Record", await asyncio.to_thread(dbm.status_summary, settings))
        e2e_dispatch = cast("list[Record]", await asyncio.to_thread(dbm.list_dispatch_runs, settings, limit=80))
        summary = md.build_dashboard_summary(
            data=data, now_ts=now_ts, e2e_status_summary=e2e_status, e2e_dispatch_runs=e2e_dispatch,
        )
        filter_summary_window(summary, since_ts=since_ts, until_ts=until_ts)
        return summary

    async def api_domain_series(
        domain: str, req: fastapi.Request, range_label: Annotated[str, fastapi.Query(alias="range")] = "24h",
        since_ts: float | None = None, until_ts: float | None = None,
    ) -> Record:
        access.require_monitoring_access(req)
        settings = context.settings
        now_ts = time.time()
        since_ts, until_ts = _series_bounds(now_ts, range_label, since_ts, until_ts)
        data = await context.monitor_data()
        return md.domain_timeseries(
            data=data, domain=domain, since_ts=since_ts, until_ts=until_ts,
            max_points=int(settings.dashboard_max_points),
        )

    async def api_signal_series(
        signal: str, req: fastapi.Request, range_label: Annotated[str, fastapi.Query(alias="range")] = "24h",
        since_ts: float | None = None, until_ts: float | None = None,
    ) -> Record:
        access.require_monitoring_access(req)
        settings = context.settings
        now_ts = time.time()
        since_ts, until_ts = _series_bounds(now_ts, range_label, since_ts, until_ts)
        data = await context.monitor_data()
        return md.signal_timeseries(
            data=data, signal=signal, since_ts=since_ts, until_ts=until_ts,
            max_points=int(settings.dashboard_max_points),
        )

    for prefix in ("/api/v1", "/dashboard/api/v1"):
        app.add_api_route(f"{prefix}/monitoring/summary", api_monitoring_summary, response_model=dict)
    for prefix in ("/api/v1", "/dashboard/api/v1"):
        app.add_api_route(f"{prefix}/monitoring/domains/{{domain}}/series", api_domain_series, response_model=dict)
    for prefix in ("/api/v1", "/dashboard/api/v1"):
        app.add_api_route(f"{prefix}/monitoring/signals/{{signal}}/series", api_signal_series, response_model=dict)
