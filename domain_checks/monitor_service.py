# Copyright (c) 2026 PitchAI. All rights reserved.
"""Top-level resource ownership and monitor-cycle orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from playwright.async_api import async_playwright

from domain_checks.event_bus import EventBusOutbox
from domain_checks.monitor_browser import BrowserManager, run_browser_lifecycle
from domain_checks.monitor_context import MonitorContext
from domain_checks.monitor_cycle_api import run_api_cycle
from domain_checks.monitor_cycle_container import run_container_cycle
from domain_checks.monitor_cycle_domains import DomainResources, run_domain_cycle
from domain_checks.monitor_cycle_health import run_health_cycles
from domain_checks.monitor_cycle_heartbeat import load_heartbeat_schedule, run_heartbeat_cycle
from domain_checks.monitor_cycle_meta import run_meta_cycle
from domain_checks.monitor_cycle_network import run_dns_cycle, run_tls_cycle
from domain_checks.monitor_cycle_proxy import run_proxy_cycle
from domain_checks.monitor_cycle_slo_red import run_red_cycle, run_slo_cycle
from domain_checks.monitor_cycle_synthetic import run_synthetic_cycle
from domain_checks.monitor_cycle_web_vitals import run_web_vitals_cycle
from domain_checks.monitor_dispatch import DispatchCoordinator
from domain_checks.monitor_events import MonitorEvents, persisted_outbox_entries
from domain_checks.monitor_runtime_state import runtime_state
from domain_checks.monitor_settings import load_settings
from domain_checks.monitor_state import load_monitor_state
from domain_checks.monitor_state_payload import prune_signals
from domain_checks.monitor_state_schema import default_monitor_state

if TYPE_CHECKING:
    from pathlib import Path

    from domain_checks.monitor_context import ChunkSender, DomainCycle
    from domain_checks.monitor_cycle_domains import DomainChecker
    from domain_checks.monitor_cycle_heartbeat import HeartbeatSchedule
    from domain_checks.monitor_runtime_state import RuntimeState
    from domain_checks.monitor_settings import MonitorSettings

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class ServiceDependencies:
    """Main-module hooks retained for imports and monkeypatch-based tests."""

    checker: DomainChecker
    send_chunks: ChunkSender


@dataclass(frozen=True)
class _LoadedMonitor:
    """Validated settings, mutable state, event lifecycle, and disabled inventory."""

    settings: MonitorSettings
    state: RuntimeState
    events: MonitorEvents
    disabled_domains: list[str]


@dataclass(frozen=True)
class _LoopResources:
    """Stable injected dependencies and concurrency controls for the loop."""

    dependencies: ServiceDependencies
    check_semaphore: asyncio.Semaphore
    browser_semaphore: asyncio.Semaphore


def _event_outbox(settings: MonitorSettings, state: RuntimeState) -> EventBusOutbox | None:
    config = settings.connections.event_bus
    if config is None:
        LOGGER.warning("PitchAI Events Bus delivery is not configured")
        return None
    entries = persisted_outbox_entries(state.collections.event_bus_outbox)
    outbox = EventBusOutbox(config, entries=entries)
    LOGGER.info("Loaded PitchAI Events Bus outbox pending=%s", outbox.pending_count)
    return outbox


async def _run_cycles(
    ctx: MonitorContext,
    resources: DomainResources,
    manager: BrowserManager,
    schedule: HeartbeatSchedule,
) -> DomainCycle:
    cycle = await run_domain_cycle(ctx, resources)
    health = await run_health_cycles(ctx, cycle)
    await run_slo_cycle(ctx, cycle)
    await run_tls_cycle(ctx, cycle)
    await run_dns_cycle(ctx, cycle)
    await run_red_cycle(ctx, cycle)
    await run_api_cycle(ctx, cycle)
    await run_container_cycle(ctx, cycle)
    await run_proxy_cycle(ctx, cycle)
    await run_synthetic_cycle(ctx, cycle, manager.browser)
    await run_web_vitals_cycle(ctx, cycle, manager.browser)
    await run_browser_lifecycle(ctx, cycle, manager)
    ctx.dispatcher.prune()
    await run_heartbeat_cycle(ctx, cycle, health, schedule)
    prune_signals(ctx.state, before_ts=time.time() - ctx.settings.core.history_retention_seconds)
    await ctx.events.flush(ctx.http_client)
    _ = ctx.events.persist()
    return cycle


async def _monitor_loop(
    ctx: MonitorContext,
    dependencies: ServiceDependencies,
    manager: BrowserManager,
    *,
    once: bool,
) -> int:
    schedule = load_heartbeat_schedule(ctx.settings)
    resources = _LoopResources(
        dependencies=dependencies,
        check_semaphore=asyncio.Semaphore(ctx.settings.core.check_concurrency),
        browser_semaphore=asyncio.Semaphore(ctx.settings.core.browser_concurrency),
    )
    manager.browser = await manager.ensure(time.time())
    try:
        return await _cycle_loop(
            ctx,
            manager,
            schedule,
            resources,
            once=once,
        )
    finally:
        await manager.close()


async def _cycle_loop(
    ctx: MonitorContext,
    manager: BrowserManager,
    schedule: HeartbeatSchedule,
    loop_resources: _LoopResources,
    *,
    once: bool,
) -> int:
    while True:
        started = time.time()
        LOGGER.info("Running check cycle")
        manager.browser = await manager.ensure(started)
        resources = DomainResources(
            browser=manager.browser,
            checker=loop_resources.dependencies.checker,
            check_semaphore=loop_resources.check_semaphore,
            browser_semaphore=loop_resources.browser_semaphore,
        )
        cycle = await _run_cycles(ctx, resources, manager, schedule)
        if once:
            return 0
        elapsed = time.time() - started
        browser_connected = manager.browser is not None and manager.browser.is_connected()
        await run_meta_cycle(
            ctx,
            cycle,
            elapsed_seconds=elapsed,
            browser_connected=browser_connected,
        )
        await ctx.events.flush(ctx.http_client)
        _ = ctx.events.persist()
        sleep_for = max(0.0, ctx.settings.core.interval_seconds - elapsed)
        LOGGER.info(
            "Cycle complete elapsed_seconds=%s sleep_seconds=%s",
            round(elapsed, 3),
            round(sleep_for, 3),
        )
        await asyncio.sleep(sleep_for)


def _load_monitor(config_path: Path) -> _LoadedMonitor:
    settings = load_settings(config_path)
    payload = load_monitor_state(settings.state_path) if settings.state_path is not None else default_monitor_state()
    state = runtime_state(payload)
    outbox = _event_outbox(settings, state)
    events = MonitorEvents(state=state, outbox=outbox, state_path=settings.state_path)
    now = time.time()
    disabled_entries = [entry for entry in settings.inventory.entries if entry.is_disabled(now)]
    disabled = [entry.domain for entry in disabled_entries]
    return _LoadedMonitor(
        settings=settings,
        state=state,
        events=events,
        disabled_domains=disabled,
    )


async def run_monitor(
    config_path: Path,
    *,
    once: bool,
    dependencies: ServiceDependencies,
) -> int:
    """Load monitor state, own external clients, and run cycles.

    Returns:
        Zero after an explicitly requested single cycle.
    """
    loaded = _load_monitor(config_path)
    settings = loaded.settings
    state = loaded.state
    events = loaded.events
    now = time.time()
    LOGGER.info(
        "Starting service monitor domains=%s disabled_domains=%s interval_seconds=%s chromium_path=%s",
        list(settings.inventory.entries_by_domain),
        loaded.disabled_domains,
        settings.core.interval_seconds,
        settings.chromium_path,
    )
    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as client:
        dispatcher = DispatchCoordinator(
            http_client=client,
            telegram=settings.connections.telegram,
            config=settings.connections.dispatch,
            dispatch_state=settings.connections.dispatch_state,
            runtime_state=state,
        )
        context = MonitorContext(
            settings=settings,
            state=state,
            events=events,
            dispatcher=dispatcher,
            http_client=client,
            send_chunks=dependencies.send_chunks,
        )
        events.append(
            "service_started",
            occurred_at=now,
            interval_seconds=settings.core.interval_seconds,
            monitored_domains=len(settings.inventory.entries) - len(loaded.disabled_domains),
        )
        await events.flush(client)
        events.persist()
        async with async_playwright() as playwright:
            manager = BrowserManager(
                browser_type=playwright.chromium,
                executable_path=settings.chromium_path,
                minimum_available_mb=settings.core.browser_min_mem_available_mb,
                state=state.metadata.browser,
            )
            return await _monitor_loop(context, dependencies, manager, once=once)
