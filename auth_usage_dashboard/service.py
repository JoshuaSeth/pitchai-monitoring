from __future__ import annotations

import asyncio
import copy
import logging
import time
from datetime import datetime
from typing import Any, Protocol

from .capacity import build_dashboard_snapshot, isoformat, utc_now
from .settings import DashboardSettings


LOG = logging.getLogger(__name__)


class StateSource(Protocol):
    def read_accounts(self) -> list[dict[str, Any]]: ...

    def probe_accounts(self, accounts: list[dict[str, Any]]) -> dict[str, str]: ...

    def close(self) -> None: ...


class CapacityService:
    def __init__(self, settings: DashboardSettings, source: StateSource) -> None:
        self.settings = settings
        self.source = source
        self._snapshot: dict[str, Any] | None = None
        self._refresh_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._last_probe_monotonic: float | None = None
        self._last_safe_probe_at: datetime | None = None
        self._last_probe_errors: dict[str, str] = {}

    async def start(self) -> None:
        if self.settings.safe_probe_enabled and not self.settings.probe_on_startup:
            self._last_probe_monotonic = time.monotonic()
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
                due = self._probe_due()
                if self.settings.safe_probe_enabled and (force_probe or due):
                    self._last_probe_monotonic = time.monotonic()
                    self._last_probe_errors = await asyncio.to_thread(self.source.probe_accounts, raw_accounts)
                    self._last_safe_probe_at = utc_now()
                    raw_accounts = await asyncio.to_thread(self.source.read_accounts)
                now = utc_now()
                self._snapshot = build_dashboard_snapshot(
                    raw_accounts,
                    now=now,
                    stale_after_seconds=self.settings.stale_after_seconds,
                    min_five_hour_remaining_percent=self.settings.min_five_hour_remaining_percent,
                    probe_errors=self._last_probe_errors,
                    source_error=None,
                    last_safe_probe_at=self._last_safe_probe_at,
                    probe_interval_seconds=self.settings.safe_probe_interval_seconds,
                )
            except Exception as exc:
                LOG.warning("Capacity snapshot refresh failed: %s", type(exc).__name__)
                now = utc_now()
                if self._snapshot is None:
                    self._snapshot = build_dashboard_snapshot(
                        [],
                        now=now,
                        stale_after_seconds=self.settings.stale_after_seconds,
                        min_five_hour_remaining_percent=self.settings.min_five_hour_remaining_percent,
                        source_error=type(exc).__name__,
                        last_safe_probe_at=self._last_safe_probe_at,
                        probe_interval_seconds=self.settings.safe_probe_interval_seconds,
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

    async def _refresh_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.snapshot_refresh_seconds)
            except asyncio.TimeoutError:
                await self.refresh(force_probe=False)
