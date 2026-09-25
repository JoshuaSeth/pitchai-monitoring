# Copyright (c) 2026 PitchAI. All rights reserved.
"""Authenticated monitoring summary and timeseries API routes."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request

from e2e_registry import db as dbm
from e2e_registry import monitor_dashboard as md
from e2e_registry.app_context import context_from_request
from e2e_registry.models import JsonObject, JsonValue, require_float

if TYPE_CHECKING:
    from e2e_registry.app_context import RegistryAppContext
    from e2e_registry.monitor_types import MonitorRecord, MonitorRecords

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, JsonObject, JsonValue)


@router.get("/dashboard/api/v1/monitoring/summary")
@router.get("/api/v1/monitoring/summary")
async def _api_monitoring_summary(
    request: Request,
    range_label: Annotated[str, Query(alias="range")] = "24h",
) -> JsonObject:
    context = context_from_request(request)
    context.require_monitoring_access(request)
    now_ts = time.time()
    since_ts, until_ts = md.resolve_range(now_ts=now_ts, range_label=range_label)
    summary = await _load_dashboard_summary(context, now_ts=now_ts)
    _filter_summary_range(summary, since_ts=since_ts, until_ts=until_ts)
    return summary


async def _load_dashboard_summary(
    context: RegistryAppContext,
    *,
    now_ts: float,
) -> JsonObject:
    data = await context.monitor_data()
    e2e_status = await asyncio.to_thread(dbm.status_summary, context.settings)
    e2e_dispatch = await asyncio.to_thread(dbm.list_dispatch_runs, context.settings, limit=80)
    return cast(
        "JsonObject",
        md.build_dashboard_summary(
            data=data,
            now_ts=now_ts,
            e2e_status_summary=cast("MonitorRecord", e2e_status),
            e2e_dispatch_runs=cast("MonitorRecords", e2e_dispatch),
        ),
    )


def _filter_summary_range(summary: JsonObject, *, since_ts: float, until_ts: float) -> None:
    raw_events = summary.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    summary["events"] = cast(
        "JsonValue",
        entries_in_range(events, since_ts=since_ts, until_ts=until_ts),
    )

    raw_dispatch = summary.get("dispatch")
    dispatch = raw_dispatch if isinstance(raw_dispatch, dict) else {}
    raw_recent = dispatch.get("recent")
    recent = raw_recent if isinstance(raw_recent, list) else []
    dispatch["recent"] = cast(
        "JsonValue",
        entries_in_range(
            recent,
            since_ts=since_ts,
            until_ts=until_ts,
            include_missing=True,
        ),
    )
    summary["dispatch"] = dispatch


@router.get("/dashboard/api/v1/monitoring/domains/{domain}/series")
@router.get("/api/v1/monitoring/domains/{domain}/series")
async def _api_domain_series(
    domain: str,
    request: Request,
    range_label: Annotated[str, Query(alias="range")] = "24h",
    since_ts: float | None = None,
    until_ts: float | None = None,
) -> JsonObject:
    context = context_from_request(request)
    context.require_monitoring_access(request)
    resolved_since, resolved_until = resolve_requested_range(
        now_ts=time.time(),
        range_label=range_label,
        since_ts=since_ts,
        until_ts=until_ts,
    )
    data = await context.monitor_data()
    result = md.domain_timeseries(
        data=data,
        domain=domain,
        since_ts=resolved_since,
        until_ts=resolved_until,
        max_points=int(context.settings.dashboard_max_points),
    )
    return cast("JsonObject", result)


@router.get("/dashboard/api/v1/monitoring/signals/{signal}/series")
@router.get("/api/v1/monitoring/signals/{signal}/series")
async def _api_signal_series(
    signal: str,
    request: Request,
    range_label: Annotated[str, Query(alias="range")] = "24h",
    since_ts: float | None = None,
    until_ts: float | None = None,
) -> JsonObject:
    context = context_from_request(request)
    context.require_monitoring_access(request)
    resolved_since, resolved_until = resolve_requested_range(
        now_ts=time.time(),
        range_label=range_label,
        since_ts=since_ts,
        until_ts=until_ts,
    )
    data = await context.monitor_data()
    result = md.signal_timeseries(
        data=data,
        signal=signal,
        since_ts=resolved_since,
        until_ts=resolved_until,
        max_points=int(context.settings.dashboard_max_points),
    )
    return cast("JsonObject", result)


def resolve_requested_range(
    *,
    now_ts: float,
    range_label: str,
    since_ts: float | None,
    until_ts: float | None,
) -> tuple[float, float]:
    """Fill missing bounds from a named range and validate ordering.

    Returns:
        The inclusive timestamp bounds.

    Raises:
        HTTPException: If the upper bound precedes the lower bound.
    """
    default_since, default_until = md.resolve_range(now_ts=now_ts, range_label=range_label)
    resolved_since = default_since if since_ts is None else float(since_ts)
    resolved_until = default_until if until_ts is None else float(until_ts)
    if resolved_until < resolved_since:
        raise HTTPException(status_code=400, detail="invalid_range")
    return float(resolved_since), float(resolved_until)


def entries_in_range(
    entries: list[JsonValue],
    *,
    since_ts: float,
    until_ts: float,
    include_missing: bool = False,
) -> list[JsonObject]:
    """Keep timestamped JSON objects in the selected dashboard range.

    Returns:
        The entries whose timestamps fall within the requested range.
    """
    selected: list[JsonObject] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_timestamp = entry.get("ts")
        timestamp_is_missing = not raw_timestamp
        if timestamp_is_missing:
            if include_missing:
                selected.append(entry)
            continue
        timestamp = require_float(raw_timestamp, label="monitoring entry timestamp")
        if since_ts <= timestamp <= until_ts:
            selected.append(entry)
    return selected


ROUTE_HANDLERS = (_api_monitoring_summary, _api_domain_series, _api_signal_series)
