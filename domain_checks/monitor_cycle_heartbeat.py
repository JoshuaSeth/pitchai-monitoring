# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scheduled heartbeat and authenticated external-E2E summary cycle."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

import httpx

from domain_checks.monitor_heartbeat import (
    HeartbeatHealth,
    HeartbeatSnapshot,
    HeartbeatTiming,
    build_heartbeat,
)
from domain_checks.monitor_time import load_timezone, parse_hhmm
from domain_checks.monitor_values import float_value, json_array, object_config
from domain_checks.telegram import redact_telegram_response

if TYPE_CHECKING:
    from datetime import time, tzinfo

    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.monitor_cycle_health import HealthCycle
    from domain_checks.monitor_settings import MonitorSettings
    from domain_checks.types import JsonObject, JsonValue

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class ExternalE2E:
    """Authenticated external test-registry connection settings."""

    enabled: bool
    base_url: str
    token: str
    timeout_seconds: float


@dataclass
class HeartbeatClock:
    """Validated wall-clock heartbeat timing configuration."""

    timezone: tzinfo
    timezone_name: str
    times: list[time]
    tolerance_seconds: int
    started_at: datetime


@dataclass
class HeartbeatSchedule:
    """Validated heartbeat configuration and sent-day state."""

    enabled: bool
    clock: HeartbeatClock
    external: ExternalE2E
    last_sent: dict[str, str] = field(default_factory=dict)

    def due(self) -> tuple[datetime, str] | None:
        """Return the due wall-clock label, if any.

        Returns:
            Current zoned time and due HH:MM label, or ``None``.
        """
        now = datetime.now(self.clock.timezone)
        today = now.date().isoformat()
        for scheduled in self.clock.times:
            label = scheduled.strftime("%H:%M")
            if self.last_sent.get(label) == today:
                continue
            due_at = datetime(
                year=now.year,
                month=now.month,
                day=now.day,
                hour=scheduled.hour,
                minute=scheduled.minute,
                tzinfo=self.clock.timezone,
            )
            if due_at <= now < due_at + timedelta(
                seconds=self.clock.tolerance_seconds,
            ):
                return now, label
        return None


def load_heartbeat_schedule(settings: MonitorSettings) -> HeartbeatSchedule:
    """Validate heartbeat and external registry configuration.

    Returns:
        The initialized schedule state.

    Raises:
        ValueError: Heartbeats are enabled without a valid schedule.
    """
    config = object_config(settings.config, "heartbeat")
    enabled = bool(config.get("enabled", False))
    raw_times = json_array(config.get("times"))
    if enabled and not raw_times:
        message = "heartbeat.times must be a non-empty list of HH:MM strings when heartbeat.enabled=true"
        raise ValueError(message)
    timezone_name = str(config.get("timezone") or "UTC")
    timezone = load_timezone(timezone_name)
    times = [parse_hhmm(value) for value in raw_times]
    external_config = object_config(settings.config, "external_e2e")
    monitor_token = os.getenv("E2E_REGISTRY_MONITOR_TOKEN", "").strip()
    admin_token = os.getenv("E2E_REGISTRY_ADMIN_TOKEN", "").strip()
    configured_token = str(external_config.get("monitor_token") or "").strip()
    external = ExternalE2E(
        enabled=bool(external_config.get("enabled", False)),
        base_url=os.getenv(
            "E2E_REGISTRY_BASE_URL",
            str(external_config.get("base_url") or ""),
        ).strip(),
        token=monitor_token or admin_token or configured_token,
        timeout_seconds=float_value(external_config.get("timeout_seconds"), default=8.0),
    )
    return HeartbeatSchedule(
        enabled=enabled,
        clock=HeartbeatClock(
            timezone=timezone,
            timezone_name=timezone_name,
            times=times,
            tolerance_seconds=max(120, settings.core.interval_seconds * 2),
            started_at=datetime.now(timezone),
        ),
        external=external,
    )


async def _fetch_external_summary(
    ctx: MonitorContext, external: ExternalE2E,
) -> JsonValue:
    url = external.base_url.rstrip("/") + "/api/v1/status/summary"
    response = await ctx.http_client.get(
        url,
        headers={"Authorization": f"Bearer {external.token}"},
        timeout=external.timeout_seconds,
    )
    _ = response.raise_for_status()
    return cast("JsonValue", response.json())


async def _external_summary(ctx: MonitorContext, external: ExternalE2E) -> JsonObject | None:
    if not external.enabled or not external.base_url:
        return None
    if not external.token:
        return {"ok": False, "error": "missing_e2e_registry_token"}
    try:
        value = await _fetch_external_summary(ctx, external)
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(value, dict):
        return {"ok": False, "error": "invalid_e2e_registry_response"}
    return value


async def run_heartbeat_cycle(
    ctx: MonitorContext,
    cycle: DomainCycle,
    health: HealthCycle,
    schedule: HeartbeatSchedule,
) -> None:
    """Send one due heartbeat with domain, host, performance, and E2E evidence."""
    if not schedule.enabled or not (cycle.results or cycle.disabled_lines):
        return
    due = schedule.due()
    if due is None:
        return
    now, label = due
    external = await _external_summary(ctx, schedule.external)
    snapshot = HeartbeatSnapshot(
        timing=HeartbeatTiming(
            now=now,
            scheduled_label=f"{label} {schedule.clock.timezone_name}",
            started_at=schedule.clock.started_at,
        ),
        results=cycle.results,
        entries=ctx.settings.inventory.entries_by_domain,
        disabled_lines=cycle.disabled_lines,
        health=HeartbeatHealth(
            host_snapshot=health.host_snapshot,
            host_violations=health.host_violations,
            performance_slow=health.performance_slow,
            external_e2e=external,
        ),
    )
    message = build_heartbeat(snapshot)
    telegram = ctx.settings.connections.telegram
    ok, responses = await ctx.send_chunks(ctx.http_client, telegram, message)
    schedule.last_sent[label] = now.date().isoformat()
    LOGGER.info(
        "Heartbeat sent scheduled=%s ok=%s telegram_last=%s",
        label,
        ok,
        redact_telegram_response(responses[-1] if responses else {}),
    )
