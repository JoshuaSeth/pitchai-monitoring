# Copyright (c) 2026 PitchAI. All rights reserved.
"""Ordered configuration, inventory and resource preparation for the native loop."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .browser_state import restore_browser_state
from .common_check import find_chromium_executable
from .config_file import load_config, load_domain_spec
from .cycle_assembly import ObservationSettings
from .cycle_health_state import CycleHealthState
from .cycle_iteration import CycleParticipants
from .cycle_persistence import CyclePersistence, restore_outbox
from .cycle_records import CycleRecords
from .cycle_settings import CycleMetricsSettings, CycleProbeSettings, CycleServiceSettings
from .cycle_startup import ChannelStartup, CycleLimits, external_heartbeat
from .dft_cycle import DftCycle, parse_cycle_config
from .domain_entries import normalize_domain_entries
from .domain_time import load_timezone
from .heartbeat_phase import HeartbeatPhase, HeartbeatSchedule
from .heartbeat_settings import load_heartbeat_settings
from .inventory import validate_domain_inventory

if TYPE_CHECKING:
    from .common_check import DomainCheckSpec
    from .config_values import ConfigValue
    from .domain_entries import DomainEntryConfig

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class MonitorInventory:
    """One validated inventory retaining spec and entry identity throughout startup."""

    entries: list[DomainEntryConfig]
    specs: dict[str, DomainCheckSpec]
    participants: CycleParticipants

    @classmethod
    def read(cls, raw: list[ConfigValue]) -> MonitorInventory:
        """Return ordered entries/specs with the existing alertable-domain selection."""
        entries = normalize_domain_entries(raw)
        by_domain = {entry.domain: entry for entry in entries}
        routed = [entry for entry in entries if entry.routes_telegram]
        alertable = {entry.domain for entry in routed}
        specs = {entry.domain: load_domain_spec(entry.raw_entry) for entry in entries}
        return cls(entries, specs, CycleParticipants(by_domain, alertable))

    def record_startup(self, chromium: str, interval: int) -> int:
        """Log the original startup inventory.

        Returns:
            The monitored count at the same startup timestamp as the disabled list.
        """
        now = time.time()
        disabled = [entry for entry in self.entries if entry.is_disabled(now)]
        names = [entry.domain for entry in self.entries]
        disabled_names = [entry.domain for entry in disabled]
        LOGGER.info("Starting service monitor domains=%s disabled_domains=%s interval_seconds=%s chromium_path=%s",
                    names, disabled_names, interval, chromium)
        return len(self.entries) - len(disabled)


@dataclass(frozen=True)
class BrowserStartup:
    """Resolved native executable and the original startup monitored-domain count."""

    executable: str
    monitored: int


def prepare_heartbeat(config: dict[str, ConfigValue], limits: CycleLimits) -> HeartbeatPhase:
    """Return the original schedule, sampling start time before registry settings."""
    settings = load_heartbeat_settings(config)
    timezone = load_timezone(settings.timezone)
    schedule = HeartbeatSchedule(timezone, datetime.now(timezone), limits.tolerance, {})
    registry = external_heartbeat(config, os.environ)
    return HeartbeatPhase(settings, schedule, registry)


@dataclass(frozen=True)
class CyclePreparation:
    """Decoded startup inputs, preserving clocks and option validation precedence."""

    config: dict[str, ConfigValue]
    limits: CycleLimits
    channels: ChannelStartup
    inventory: MonitorInventory
    heartbeat: HeartbeatPhase
    settings: ObservationSettings
    browser: BrowserStartup

    @classmethod
    def read(cls, path: Path) -> CyclePreparation:
        """Return validated configuration without reading state or creating runtime resources.

        Raises:
            ValueError: The domain inventory is empty or invalid.
            RuntimeError: Chromium cannot be resolved through its existing search.
        """
        config = load_config(path)
        validate_domain_inventory(config)
        limits = CycleLimits.read(config)
        raw_domains = config.get("domains", [])
        if not isinstance(raw_domains, list) or not raw_domains:
            message = "Config must contain a non-empty 'domains' list"
            raise ValueError(message)
        channels = ChannelStartup.read(os.environ)
        inventory = MonitorInventory.read(raw_domains)
        heartbeat = prepare_heartbeat(config, limits)
        settings = ObservationSettings(CycleMetricsSettings.read(config), CycleProbeSettings.read(config),
                                       CycleServiceSettings.read(config))
        chromium = find_chromium_executable()
        if not chromium:
            message = "Could not find a Chromium/Chrome executable (set CHROMIUM_PATH)"
            raise RuntimeError(message)
        monitored = inventory.record_startup(chromium, limits.interval)
        return cls(config, limits, channels, inventory, heartbeat, settings, BrowserStartup(chromium, monitored))


@dataclass(frozen=True)
class CycleResources:
    """The same state owner and semaphores, created after startup validation."""

    persistence: CyclePersistence
    checks: asyncio.Semaphore
    browsers: asyncio.Semaphore

    @classmethod
    def load(cls, prepared: CyclePreparation) -> CycleResources:
        """Restore existing state/journal references without adopting a new allocation.

        Returns:
            Existing records, health, outbox and browser state with original semaphore limits.
        """
        raw_path = str(os.getenv("STATE_PATH", "/data/state.json") or "").strip()
        path = Path(raw_path) if raw_path else None
        dft = DftCycle(parse_cycle_config(prepared.config.get("dft_web_access")))
        records = CycleRecords.load(path, down_after_failures=prepared.limits.down_after_failures,
                                    up_after_successes=prepared.limits.up_after_successes)
        health = CycleHealthState()
        health.host.last_snapshot = records.host_snapshot
        health.restore(records.disk)
        outbox = restore_outbox(prepared.channels.event_bus, records.disk)
        checks = asyncio.Semaphore(prepared.limits.check_concurrency)
        browsers = asyncio.Semaphore(prepared.limits.browser_concurrency)
        minimum = os.getenv("BROWSER_MIN_MEM_AVAILABLE_MB")
        raw_minimum = prepared.config.get("browser_min_mem_available_mb", 2048) if minimum is None else minimum
        browser = restore_browser_state(records.disk, raw_minimum)
        persistence = CyclePersistence(path, records, health, browser, dft, outbox)
        return cls(persistence, checks, browsers)
