from __future__ import annotations

import asyncio
import copy
import logging
import time
from datetime import datetime
from typing import Any, Protocol

from .capacity import build_dashboard_snapshot, isoformat, utc_now
from .history import UsageSampleStore
from .settings import DashboardSettings


LOG = logging.getLogger(__name__)


class StateSource(Protocol):
    def read_accounts(self) -> list[dict[str, Any]]: ...

    def probe_accounts(self, accounts: list[dict[str, Any]]) -> dict[str, str]: ...

    def probe_analytics(self, accounts: list[dict[str, Any]]) -> dict[str, str]: ...

    def close(self) -> None: ...


class CapacityService:
    def __init__(
        self,
        settings: DashboardSettings,
        source: StateSource,
        *,
        sample_store: UsageSampleStore | None = None,
    ) -> None:
        self.settings = settings
        self.source = source
        self._snapshot: dict[str, Any] | None = None
        self._refresh_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._last_probe_monotonic: float | None = None
        self._last_safe_probe_at: datetime | None = None
        self._last_probe_errors: dict[str, str] = {}
        self._last_analytics_probe_monotonic: float | None = None
        self._last_analytics_probe_at: datetime | None = None
        self._last_analytics_probe_errors: dict[str, str] = {}
        self._sample_store = sample_store
        if self._sample_store is None and settings.history_file is not None:
            self._sample_store = UsageSampleStore(
                settings.history_file,
                retention_days=settings.history_retention_days,
                sample_interval_seconds=settings.history_sample_interval_seconds,
            )

    async def start(self) -> None:
        if self.settings.safe_probe_enabled and not self.settings.probe_on_startup:
            started_at = time.monotonic()
            self._last_probe_monotonic = started_at
            self._last_analytics_probe_monotonic = started_at
        await self.refresh(force_probe=self.settings.safe_probe_enabled and self.settings.probe_on_startup)
        self._loop_task = asyncio.create_task(self._refresh_loop(), name="auth-usage-dashboard-refresh")

    async def stop(self) -> None:
        self._stop.set()
        if self._loop_task is not None:
            await self._loop_task
        await asyncio.to_thread(self.source.close)

    async def snapshot(self) -> dict[str, Any]:
        if self._snapshot is None:
            await self.refresh(force_probe=False)
        assert self._snapshot is not None
        return copy.deepcopy(self._snapshot)

    async def health(self) -> dict[str, Any]:
        snapshot = await self.snapshot()
        source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
        return {
            "status": "degraded" if source.get("error") else "ok",
            "generated_at": snapshot.get("generated_at"),
            "source_stale": bool(source.get("stale")),
        }

    async def request_manual_probe(self) -> dict[str, Any]:
        if not self.settings.safe_probe_enabled:
            await self.refresh(force_probe=False)
            return {"probe_started": False, "reason": "safe_probe_disabled", "snapshot": await self.snapshot()}
        if self._last_probe_monotonic is not None:
            elapsed = time.monotonic() - self._last_probe_monotonic
            if elapsed < self.settings.manual_probe_min_interval_seconds:
                await self.refresh(force_probe=False)
                return {
                    "probe_started": False,
                    "reason": "probe_throttled",
                    "retry_after_seconds": int(self.settings.manual_probe_min_interval_seconds - elapsed) + 1,
                    "snapshot": await self.snapshot(),
                }
        await self.refresh(force_probe=True)
        return {"probe_started": True, "reason": "manual", "snapshot": await self.snapshot()}

    async def refresh(self, *, force_probe: bool) -> None:
        async with self._refresh_lock:
            try:
                raw_accounts = await asyncio.to_thread(self.source.read_accounts)
                analytics_due = self._analytics_probe_due()
                run_analytics = self.settings.safe_probe_enabled and (force_probe or analytics_due)
                if run_analytics:
                    probe_started = time.monotonic()
                    self._last_probe_monotonic = probe_started
                    self._last_analytics_probe_monotonic = probe_started
                    self._last_analytics_probe_errors = await asyncio.to_thread(
                        self.source.probe_analytics,
                        raw_accounts,
                    )
                    self._last_probe_errors = self._last_analytics_probe_errors
                    probed_at = utc_now()
                    self._last_safe_probe_at = probed_at
                    self._last_analytics_probe_at = probed_at
                    raw_accounts = await asyncio.to_thread(self.source.read_accounts)
                elif self.settings.safe_probe_enabled and self._probe_due():
                    self._last_probe_monotonic = time.monotonic()
                    self._last_probe_errors = await asyncio.to_thread(self.source.probe_accounts, raw_accounts)
                    self._last_safe_probe_at = utc_now()
                    raw_accounts = await asyncio.to_thread(self.source.read_accounts)
                now = utc_now()
                snapshot_arguments = dict(
                    now=now,
                    stale_after_seconds=self.settings.stale_after_seconds,
                    analytics_stale_after_seconds=self.settings.analytics_stale_after_seconds,
                    min_five_hour_remaining_percent=self.settings.min_five_hour_remaining_percent,
                    probe_errors=self._last_probe_errors,
                    analytics_probe_errors=self._last_analytics_probe_errors,
                    source_error=None,
                    last_safe_probe_at=self._last_safe_probe_at,
                    last_analytics_probe_at=self._last_analytics_probe_at,
                    probe_interval_seconds=self.settings.safe_probe_interval_seconds,
                    analytics_probe_interval_seconds=self.settings.analytics_probe_interval_seconds,
                )
                base_snapshot = build_dashboard_snapshot(raw_accounts, **snapshot_arguments)
                usage_samples: list[dict[str, Any]] = []
                history_error: str | None = None
                if self._sample_store is not None:
                    try:
                        usage_samples = await asyncio.to_thread(
                            self._sample_store.record,
                            base_snapshot["accounts"],
                            at=now,
                        )
                    except (OSError, ValueError) as exc:
                        history_error = type(exc).__name__
                        LOG.warning("Usage sample persistence failed: %s", history_error)
                self._snapshot = build_dashboard_snapshot(
                    raw_accounts,
                    **snapshot_arguments,
                    usage_samples=usage_samples,
                    history_error=history_error,
                )
            except Exception as exc:
                LOG.warning("Capacity snapshot refresh failed: %s", type(exc).__name__)
                now = utc_now()
                if self._snapshot is None:
                    self._snapshot = build_dashboard_snapshot(
                        [],
                        now=now,
                        stale_after_seconds=self.settings.stale_after_seconds,
                        analytics_stale_after_seconds=self.settings.analytics_stale_after_seconds,
                        min_five_hour_remaining_percent=self.settings.min_five_hour_remaining_percent,
                        source_error=type(exc).__name__,
                        last_safe_probe_at=self._last_safe_probe_at,
                        last_analytics_probe_at=self._last_analytics_probe_at,
                        probe_interval_seconds=self.settings.safe_probe_interval_seconds,
                        analytics_probe_interval_seconds=self.settings.analytics_probe_interval_seconds,
                    )
                else:
                    snapshot = copy.deepcopy(self._snapshot)
                    snapshot["generated_at"] = isoformat(now)
                    snapshot["source"]["stale"] = True
                    snapshot["source"]["error"] = type(exc).__name__
                    snapshot["warnings"] = [
                        {"severity": "critical", "code": "source_error", "message": "Broker state refresh failed"},
                        *[item for item in snapshot.get("warnings", []) if item.get("code") != "source_error"],
                    ]
                    self._snapshot = snapshot

    def _probe_due(self) -> bool:
        if self._last_probe_monotonic is None:
            return True
        return time.monotonic() - self._last_probe_monotonic >= self.settings.safe_probe_interval_seconds

    def _analytics_probe_due(self) -> bool:
        if self._last_analytics_probe_monotonic is None:
            return True
        return (
            time.monotonic() - self._last_analytics_probe_monotonic
            >= self.settings.analytics_probe_interval_seconds
        )

    async def _refresh_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.snapshot_refresh_seconds)
            except asyncio.TimeoutError:
                await self.refresh(force_probe=False)
