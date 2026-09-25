# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run cadence-aware dashboard probes against the configured state source."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from .service_state import probe_due
from .value_parsing import utc_now

if TYPE_CHECKING:
    from .json_contract import JsonObject
    from .service_state import ServiceRuntime, StateSource
    from .settings import DashboardSettings


async def read_and_probe_source(
    source: StateSource,
    runtime: ServiceRuntime,
    settings: DashboardSettings,
    *,
    force_probe: bool,
) -> list[JsonObject]:
    """Read current source state and run whichever bounded probe is due.

    Returns:
        The refreshed source accounts.

    """
    raw_accounts = await asyncio.to_thread(source.read_accounts)
    analytics_due = probe_due(
        runtime.analytics_probe,
        interval_seconds=settings.analytics_probe_interval_seconds,
    )
    if settings.safe_probe_enabled and (force_probe or analytics_due):
        return await _run_analytics_probe(source, runtime, raw_accounts)
    safe_due = probe_due(
        runtime.safe_probe,
        interval_seconds=settings.safe_probe_interval_seconds,
    )
    if settings.safe_probe_enabled and safe_due:
        return await _run_safe_probe(source, runtime, raw_accounts)
    return raw_accounts


async def _run_analytics_probe(
    source: StateSource,
    runtime: ServiceRuntime,
    raw_accounts: list[JsonObject],
) -> list[JsonObject]:
    started_at = time.monotonic()
    runtime.safe_probe.last_monotonic = started_at
    runtime.analytics_probe.last_monotonic = started_at
    errors = await asyncio.to_thread(source.probe_analytics, raw_accounts)
    runtime.analytics_probe.errors = errors
    runtime.safe_probe.errors = errors
    probed_at = utc_now()
    runtime.safe_probe.last_at = probed_at
    runtime.analytics_probe.last_at = probed_at
    return await asyncio.to_thread(source.read_accounts)


async def _run_safe_probe(
    source: StateSource,
    runtime: ServiceRuntime,
    raw_accounts: list[JsonObject],
) -> list[JsonObject]:
    runtime.safe_probe.last_monotonic = time.monotonic()
    runtime.safe_probe.errors = await asyncio.to_thread(
        source.probe_accounts,
        raw_accounts,
    )
    runtime.safe_probe.last_at = utc_now()
    return await asyncio.to_thread(source.read_accounts)
