# Copyright (c) 2026 PitchAI. All rights reserved.
"""Refresh and serve coherent authentication usage snapshots."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import TYPE_CHECKING

from .capacity import build_dashboard_snapshot
from .history import UsageSampleStore
from .service_failures import SourceFailureInputs, source_failure_snapshot
from .service_probes import read_and_probe_source
from .service_samples import record_usage_samples
from .service_state import ServiceRuntime, StateSource
from .value_parsing import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from .json_contract import JsonObject
    from .models import DashboardSnapshot, HealthPayload, ManualProbePayload, UsageSample
    from .settings import DashboardSettings

LOG = logging.getLogger(__name__)
SOURCE_BOUNDARY_ERRORS = (OSError, RuntimeError, ValueError)


class CapacityService:
    """Refresh dashboard state while containing declared source failures."""

    def __init__(
        self,
        settings: DashboardSettings,
        source: StateSource,
        *,
        sample_store: UsageSampleStore | None = None,
    ) -> None:
        """Initialize the service and its bounded mutable runtime."""
        self.settings: DashboardSettings = settings
        self.source: StateSource = source
        self.runtime: ServiceRuntime = ServiceRuntime()
        self.sample_store: UsageSampleStore | None = sample_store
        if self.sample_store is None and settings.history_file is not None:
            self.sample_store = UsageSampleStore(
                settings.history_file,
                retention_days=settings.history_retention_days,
                sample_interval_seconds=settings.history_sample_interval_seconds,
            )

    async def start(self) -> None:
        """Build the initial snapshot and start periodic refreshes."""
        if self.settings.safe_probe_enabled and not self.settings.probe_on_startup:
            started_at = time.monotonic()
            self.runtime.safe_probe.last_monotonic = started_at
            self.runtime.analytics_probe.last_monotonic = started_at
        force_probe = self.settings.safe_probe_enabled and self.settings.probe_on_startup
        await self.refresh(force_probe=force_probe)
        self.runtime.loop_task = asyncio.create_task(
            self._refresh_loop(),
            name="auth-usage-dashboard-refresh",
        )

    async def stop(self) -> None:
        """Stop periodic work and close source resources."""
        self.runtime.stop.set()
        if self.runtime.loop_task is not None:
            await self.runtime.loop_task
        await asyncio.to_thread(self.source.close)

    async def snapshot(self) -> DashboardSnapshot:
        """Return an isolated copy of the latest snapshot.

        Raises:
            RuntimeError: If the operation cannot satisfy its runtime contract.

        """
        if self.runtime.snapshot is None:
            await self.refresh(force_probe=False)
        if self.runtime.snapshot is None:
            msg = "capacity snapshot is unavailable after refresh"
            raise RuntimeError(msg)
        return copy.deepcopy(self.runtime.snapshot)

    async def health(self) -> HealthPayload:
        """Return the bounded public health shape."""
        snapshot = await self.snapshot()
        source = snapshot["source"]
        return {
            "status": "degraded" if source.get("error") else "ok",
            "generated_at": snapshot["generated_at"],
            "source_stale": source["stale"],
        }

    async def request_manual_probe(self) -> ManualProbePayload:
        """Run a manually requested probe when cadence policy permits.

        Returns:
            The resulting value.

        """
        if not self.settings.safe_probe_enabled:
            await self.refresh(force_probe=False)
            return {
                "probe_started": False,
                "reason": "safe_probe_disabled",
                "snapshot": await self.snapshot(),
            }
        last_probe = self.runtime.safe_probe.last_monotonic
        if last_probe is not None:
            elapsed = time.monotonic() - last_probe
            minimum_interval = self.settings.manual_probe_min_interval_seconds
            if elapsed < minimum_interval:
                await self.refresh(force_probe=False)
                return {
                    "probe_started": False,
                    "reason": "probe_throttled",
                    "retry_after_seconds": int(minimum_interval - elapsed) + 1,
                    "snapshot": await self.snapshot(),
                }
        await self.refresh(force_probe=True)
        return {
            "probe_started": True,
            "reason": "manual",
            "snapshot": await self.snapshot(),
        }

    async def refresh(self, *, force_probe: bool) -> None:
        """Refresh from source, allowing unexpected implementation defects to fail."""
        async with self.runtime.refresh_lock:
            raw_accounts = await self._refresh_source(force_probe=force_probe)
            if raw_accounts is None:
                return
            now = utc_now()
            base_snapshot = self._build_snapshot(raw_accounts, now=now)
            usage_samples, history_error = await record_usage_samples(
                self.sample_store,
                base_snapshot,
                now=now,
            )
            self.runtime.snapshot = self._build_snapshot(
                raw_accounts,
                now=now,
                usage_samples=usage_samples,
                history_error=history_error,
            )

    async def _refresh_source(self, *, force_probe: bool) -> list[JsonObject] | None:
        try:
            return await self._read_and_probe_source(force_probe=force_probe)
        except SOURCE_BOUNDARY_ERRORS as exc:
            self._contain_source_failure(exc)
            return None

    async def _read_and_probe_source(self, *, force_probe: bool) -> list[JsonObject]:
        """Read current source state and run whichever bounded probe is due.

        Returns:
            The resulting collection.

        """
        return await read_and_probe_source(
            self.source,
            self.runtime,
            self.settings,
            force_probe=force_probe,
        )

    def _contain_source_failure(
        self,
        error: OSError | RuntimeError | ValueError,
    ) -> None:
        error_name = type(error).__name__
        LOG.warning("Capacity source refresh failed: %s", error_name)
        inputs = SourceFailureInputs(
            self.settings,
            utc_now(),
            error_name,
            self.runtime.safe_probe.last_at,
            self.runtime.analytics_probe.last_at,
        )
        self.runtime.snapshot = source_failure_snapshot(self.runtime.snapshot, inputs)

    def _build_snapshot(
        self,
        raw_accounts: list[JsonObject],
        *,
        now: datetime,
        usage_samples: list[UsageSample] | None = None,
        history_error: str | None = None,
    ) -> DashboardSnapshot:
        return build_dashboard_snapshot(
            raw_accounts,
            now=now,
            stale_after_seconds=self.settings.stale_after_seconds,
            analytics_stale_after_seconds=self.settings.analytics_stale_after_seconds,
            min_five_hour_remaining_percent=(self.settings.min_five_hour_remaining_percent),
            probe_errors=self.runtime.safe_probe.errors,
            analytics_probe_errors=self.runtime.analytics_probe.errors,
            source_error=None,
            last_safe_probe_at=self.runtime.safe_probe.last_at,
            last_analytics_probe_at=self.runtime.analytics_probe.last_at,
            probe_interval_seconds=self.settings.safe_probe_interval_seconds,
            analytics_probe_interval_seconds=(self.settings.analytics_probe_interval_seconds),
            usage_samples=usage_samples,
            history_error=history_error,
        )

    async def _refresh_loop(self) -> None:
        while not self.runtime.stop.is_set():
            try:
                _ = await asyncio.wait_for(
                    self.runtime.stop.wait(),
                    timeout=self.settings.snapshot_refresh_seconds,
                )
            except TimeoutError:
                await self.refresh(force_probe=False)


__all__ = ["CapacityService", "StateSource"]
