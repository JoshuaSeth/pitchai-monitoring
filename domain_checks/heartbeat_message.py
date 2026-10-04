# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure heartbeat assembly with the existing keyword caller contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict, Unpack

from .heartbeat_external import external_lines
from .heartbeat_sections import host_lines, performance_lines
from .message_performance import format_ms

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from .common_check import DomainCheckResult
    from .domain_entries import DomainEntryConfig
    from .event_bus_delivery import JsonObject


class HeartbeatInputs(TypedDict):
    """Existing required observations and optional already observed sections."""

    now: datetime
    scheduled_label: str
    started_at: datetime
    results: dict[str, DomainCheckResult]
    domain_entries: NotRequired[dict[str, DomainEntryConfig] | None]
    disabled_lines: NotRequired[list[str] | None]
    host_snap: NotRequired[JsonObject | None]
    host_violations: NotRequired[list[str] | None]
    perf_slow: NotRequired[list[JsonObject] | None]
    external_e2e: NotRequired[JsonObject | None]


def format_uptime(delta: timedelta) -> str:
    """Return the original nonnegative days/hours/minutes/seconds display."""
    seconds = max(0, int(delta.total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, remainder = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02}h {minutes:02}m"
    if hours:
        return f"{hours}h {minutes:02}m"
    return f"{minutes}m {remainder:02}s"


def build_heartbeat_message(**inputs: Unpack[HeartbeatInputs]) -> str:
    """Return the existing section order and single trailing newline."""
    lines = [
        "Heartbeat: service-monitoring is running ✅",
        f"Scheduled: {inputs['scheduled_label']}",
        f"Now: {inputs['now'].strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Uptime: {format_uptime(inputs['now'] - inputs['started_at'])}",
    ]
    snapshot = inputs.get("host_snap")
    if isinstance(snapshot, dict) and snapshot:
        lines.extend(host_lines(snapshot, inputs.get("host_violations")))
    slow = inputs.get("perf_slow")
    if slow is not None:
        lines.extend(performance_lines(slow))
    external = inputs.get("external_e2e")
    if external is not None:
        lines.extend(external_lines(external))
    lines.extend(("", "Domains (HTTP / Browser):"))
    entries = inputs.get("domain_entries") or {}
    for domain in sorted(inputs["results"]):
        result = inputs["results"][domain]
        lines.append(_domain_line(domain, result, entries.get(domain)))
    disabled = inputs.get("disabled_lines")
    if disabled:
        lines.extend(("", "Disabled (skipped):"))
        lines.extend(disabled)
    return "\n".join(lines).strip() + "\n"


def _domain_line(domain: str, result: DomainCheckResult, entry: DomainEntryConfig | None) -> str:
    dashboard_only = bool(entry is not None and not entry.routes_telegram)
    details = result.details or {}
    http_status = details.get("status_code")
    http_ms = format_ms(details.get("http_elapsed_ms"))
    browser_ms = format_ms(details.get("browser_elapsed_ms"))
    if result.ok:
        status = f"UP ({http_status})" if http_status is not None else "UP"
        if dashboard_only:
            status += " · dashboard only (no Telegram alerts)"
    else:
        reason = result.reason or "down"
        error = details.get("error")
        if isinstance(error, str) and error.strip():
            reason = f"{reason}: {error}"
        status = f"DOWN ({reason})" if http_status is None else f"DOWN ({http_status}, {reason})"
        if dashboard_only:
            status += " · expected/dashboard only (no Telegram alert)"
    return f"- {domain}: {status} {http_ms} / {browser_ms}"
