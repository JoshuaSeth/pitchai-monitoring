# Copyright (c) 2026 PitchAI. All rights reserved.
"""Cached capacity snapshot over redacted broker state, refreshed and safely probed in the background."""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import TYPE_CHECKING, Protocol, cast

from .capacity import utc_now
from .history import UsageSampleStore
from .service_failures import FailureCapture
from .service_probes import ProbeLedger, RefreshRuntime
from .service_snapshots import RecordedHistory, current_snapshot, failed_refresh_snapshot
from .timeseries_types import optional_object

if TYPE_CHECKING:
    from datetime import datetime

    from .settings import DashboardSettings
    from .timeseries_types import JsonObject

LOG = logging.getLogger(__name__)


class StateSource(Protocol):
    """Broker inventory and no-generation probe surface read by the capacity service."""

    def read_accounts(self) -> list[JsonObject]:
        """Return the redacted metadata and state of every configured broker account."""
        raise NotImplementedError

    def probe_accounts(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Run the safe usage probe and return redacted errors keyed by account label."""
        raise NotImplementedError

    def probe_analytics(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Refresh token history and reset-bank state and return redacted errors by label."""
        raise NotImplementedError

    def close(self) -> None:
        """Release the resources owned by the source."""
        raise NotImplementedError


class CapacityService:
    """Own the cached capacity snapshot, its background refresh loop, and safe broker probes."""

    settings: DashboardSettings
    source: StateSource
    _snapshot: JsonObject | None
    _sample_store: UsageSampleStore | None
    _probes: ProbeLedger
    _runtime: RefreshRuntime

    def __init__(
        self,
        settings: DashboardSettings,
        source: StateSource,
        *,
        sample_store: UsageSampleStore | None = None,
    ) -> None:
        """Bind settings and broker source, persisting usage samples when history is configured."""
        self.settings = settings
        self.source = source
        self._snapshot = None
        self._runtime = RefreshRuntime()
        self._probes = ProbeLedger()
        self._sample_store = sample_store
        if self._sample_store is None and settings.history_file is not None:
            self._sample_store = UsageSampleStore(
                settings.history_file,
                retention_days=settings.history_retention_days,
                sample_interval_seconds=settings.history_sample_interval_seconds,
            )

    async def start(self) -> None:
        """Take the first snapshot, probing on startup only when configured, then start the loop."""
        if self.settings.safe_probe_enabled and not self.settings.probe_on_startup:
            self._probes.defer_startup_probes()
        await self.refresh(force_probe=self.settings.safe_probe_enabled and self.settings.probe_on_startup)
        self._runtime.loop_task = asyncio.create_task(self._refresh_loop(), name="auth-usage-dashboard-refresh")

    async def stop(self) -> None:
        """Stop the refresh loop, wait for it, and close the broker source."""
        self._runtime.stop.set()
        if self._runtime.loop_task is not None:
            await self._runtime.loop_task
        await asyncio.to_thread(self.source.close)

    async def snapshot(self) -> JsonObject:
        """Return an independent copy of the cached snapshot, refreshing first when none exists.

        Returns:
            The current capacity snapshot.

        Raises:
            AssertionError: If refreshing still left no snapshot.
        """
        if self._snapshot is None:
            await self.refresh(force_probe=False)
        cached = self._snapshot
        if cached is None:
            raise AssertionError
        return copy.deepcopy(cached)

    async def health(self) -> JsonObject:
        """Return the identity-free health summary of the cached snapshot.

        Returns:
            Status, generation time, and whether the broker source is stale.
        """
        snapshot = await self.snapshot()
        source = optional_object(snapshot.get("source"))
        return {
            "status": "degraded" if source.get("error") else "ok",
            "generated_at": snapshot.get("generated_at"),
            "source_stale": bool(source.get("stale")),
        }

    async def request_manual_probe(self) -> JsonObject:
        """Probe now unless probing is disabled or throttled, then return the fresh snapshot.

        Returns:
            Whether a probe started, why, any retry delay, and the current snapshot.
        """
        if not self.settings.safe_probe_enabled:
            await self.refresh(force_probe=False)
            return {"probe_started": False, "reason": "safe_probe_disabled", "snapshot": await self.snapshot()}
        elapsed = self._probes.seconds_since_probe()
        min_interval_seconds = self.settings.manual_probe_min_interval_seconds
        if elapsed is not None and elapsed < min_interval_seconds:
            await self.refresh(force_probe=False)
            return {
                "probe_started": False,
                "reason": "probe_throttled",
                "retry_after_seconds": int(min_interval_seconds - elapsed) + 1,
                "snapshot": await self.snapshot(),
            }
        await self.refresh(force_probe=True)
        return {"probe_started": True, "reason": "manual", "snapshot": await self.snapshot()}

    async def refresh(self, *, force_probe: bool) -> None:
        """Rebuild the snapshot; any failure keeps the last good capacity marked stale."""
        async with self._runtime.refresh_lock:
            with FailureCapture(Exception) as failure:
                self._snapshot = await self._refreshed_snapshot(force_probe=force_probe)
            if failure.error is None:
                return
            error_name = type(failure.error).__name__
            LOG.warning("Capacity snapshot refresh failed: %s", error_name)
            self._snapshot = failed_refresh_snapshot(
                self._snapshot,
                error_name=error_name,
                settings=self.settings,
                probes=self._probes,
                now=utc_now(),
            )

    async def _refreshed_snapshot(self, *, force_probe: bool) -> JsonObject:
        raw_accounts = await asyncio.to_thread(self.source.read_accounts)
        analytics_due = self._probes.analytics_probe_due(self.settings.analytics_probe_interval_seconds)
        run_analytics = self.settings.safe_probe_enabled and (force_probe or analytics_due)
        if run_analytics:
            await self._probes.run_analytics_probe(self.source, raw_accounts)
            raw_accounts = await asyncio.to_thread(self.source.read_accounts)
        elif self.settings.safe_probe_enabled and self._probes.probe_due(self.settings.safe_probe_interval_seconds):
            await self._probes.run_safe_probe(self.source, raw_accounts)
            raw_accounts = await asyncio.to_thread(self.source.read_accounts)
        now = utc_now()
        base_snapshot = current_snapshot(raw_accounts, settings=self.settings, probes=self._probes, now=now)
        history = await self._record_usage_samples(base_snapshot, now=now)
        return current_snapshot(raw_accounts, settings=self.settings, probes=self._probes, now=now, history=history)

    async def _record_usage_samples(
        self,
        snapshot: JsonObject,
        *,
        now: datetime,
    ) -> RecordedHistory:
        store = self._sample_store
        if store is None:
            return RecordedHistory(samples=[])
        accounts = cast("list[JsonObject]", cast("object", snapshot["accounts"]))
        samples: list[JsonObject] = []
        with FailureCapture(OSError, ValueError) as failure:
            samples = await asyncio.to_thread(store.record, accounts, at=now)
        if failure.error is None:
            return RecordedHistory(samples=samples)
        history_error = type(failure.error).__name__
        LOG.warning("Usage sample persistence failed: %s", history_error)
        return RecordedHistory(samples=[], error=history_error)

    async def _refresh_loop(self) -> None:
        stop = self._runtime.stop
        while not stop.is_set():
            with FailureCapture(TimeoutError) as wait:
                _ = await asyncio.wait_for(stop.wait(), timeout=self.settings.snapshot_refresh_seconds)
            if wait.error is not None:
                await self.refresh(force_probe=False)
