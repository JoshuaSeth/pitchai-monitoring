# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scheduled service-monitor heartbeat formatting and delivery."""

from __future__ import annotations

from dataclasses import dataclass
from operator import itemgetter
from typing import TYPE_CHECKING

from domain_checks.monitor_alerts import format_ms
from domain_checks.monitor_values import int_value, json_float, json_object

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from domain_checks.common_check import DomainCheckResult
    from domain_checks.monitor_domains import DomainEntryConfig
    from domain_checks.types import JsonObject


@dataclass(frozen=True)
class HeartbeatTiming:
    """Clock evidence rendered in a scheduled heartbeat."""

    now: datetime
    scheduled_label: str
    started_at: datetime


@dataclass(frozen=True)
class HeartbeatHealth:
    """Optional non-domain health evidence rendered in a heartbeat."""

    host_snapshot: JsonObject | None
    host_violations: list[str] | None
    performance_slow: list[JsonObject] | None
    external_e2e: JsonObject | None


@dataclass(frozen=True)
class HeartbeatSnapshot:
    """All evidence rendered in one scheduled heartbeat."""

    timing: HeartbeatTiming
    results: dict[str, DomainCheckResult]
    entries: dict[str, DomainEntryConfig]
    disabled_lines: list[str]
    health: HeartbeatHealth


def _format_uptime(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02}h {minutes:02}m"
    if hours:
        return f"{hours}h {minutes:02}m"
    return f"{minutes}m {seconds:02}s"


def _host_lines(snapshot: JsonObject, violations: list[str] | None) -> list[str]:
    lines = ["", "Host health:", f"- Status: {'DEGRADED' if violations else 'OK'}"]
    measured: list[tuple[str, float]] = []
    for path, info in json_object(snapshot.get("disk")).items():
        used_percent = json_object(info).get("used_percent")
        if used_percent is not None:
            measured.append((path, json_float(used_percent)))
    if measured:
        path, percentage = max(measured, key=itemgetter(1))
        lines.append(f"- Disk: {path} {percentage:.1f}%")
    for label, key in (
        ("Mem used", "mem_used_percent"),
        ("Swap used", "swap_used_percent"),
        ("CPU used", "cpu_used_percent"),
    ):
        value = snapshot.get(key)
        if value is not None:
            lines.append(f"- {label}: {json_float(value):.1f}%")
    if violations:
        lines.extend(["- Violations:", *(f"  - {item}" for item in violations[:5])])
    return lines


def _performance_lines(slow: list[JsonObject] | None) -> list[str]:
    if slow is None:
        return []
    if not slow:
        return ["", "Performance: OK"]
    lines = ["", f"Performance: DEGRADED (slow_domains={len(slow)})"]
    lines.extend(
        f"- {item.get('domain')}: {format_ms(item.get('http_ms'))} / {format_ms(item.get('browser_ms'))}"
        for item in slow[:5]
    )
    return lines


def _external_lines(summary: JsonObject | None) -> list[str]:
    if summary is None:
        return []
    if not bool(summary.get("ok", True)):
        error = str(summary.get("error") or "unknown error")[:300]
        return ["", "External E2E tests: ERROR", f"- {error}"]
    total = int_value(summary.get("total_tests"))
    failing = int_value(summary.get("failing_tests"))
    status = "OK" if failing <= 0 else "DEGRADED"
    return ["", f"External E2E tests: {status} (failing={failing}/{total})"]


def _domain_lines(snapshot: HeartbeatSnapshot) -> list[str]:
    lines = ["", "Domains (HTTP / Browser):"]
    for domain in sorted(snapshot.results):
        result = snapshot.results[domain]
        details = result.details
        status_code = details.get("status_code")
        status = "UP" if result.ok else f"DOWN ({result.reason})"
        if status_code is not None:
            status = f"{status} ({status_code})"
        entry = snapshot.entries.get(domain)
        if entry is not None and not entry.routes_telegram:
            status += " · dashboard only (no Telegram alerts)"
        lines.append(
            f"- {domain}: {status} {format_ms(details.get('http_elapsed_ms'))} / "
            f"{format_ms(details.get('browser_elapsed_ms'))}",
        )
    if snapshot.disabled_lines:
        lines.extend(("", "Disabled (skipped):", *snapshot.disabled_lines))
    return lines


def build_heartbeat(snapshot: HeartbeatSnapshot) -> str:
    """Render one service-monitor heartbeat message.

    Returns:
        The complete operator-facing heartbeat text.
    """
    timing = snapshot.timing
    health = snapshot.health
    lines = [
        "Heartbeat: service-monitoring is running ✅",
        f"Scheduled: {timing.scheduled_label}",
        f"Now: {timing.now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Uptime: {_format_uptime(timing.now - timing.started_at)}",
    ]
    if health.host_snapshot:
        lines.extend(_host_lines(health.host_snapshot, health.host_violations))
    lines.extend(_performance_lines(health.performance_slow))
    lines.extend(_external_lines(health.external_e2e))
    lines.extend(_domain_lines(snapshot))
    return "\n".join(lines).strip() + "\n"
