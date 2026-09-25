# Copyright (c) 2026 PitchAI. All rights reserved.
"""Collect routed proxy-header and bounded Nginx-log observations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from domain_checks.metrics_nginx import (
    compute_access_window_stats,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)
from domain_checks.metrics_proxy import check_upstream_header_expectations
from domain_checks.monitor_time import load_timezone
from domain_checks.monitor_values import int_value, optional_float

if TYPE_CHECKING:
    from domain_checks.metrics_nginx import (
        NginxAccessWindowStats,
        NginxUpstreamErrorEvent,
        NginxUpstreamSummary,
    )
    from domain_checks.metrics_proxy import ProxyIssue
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.types import JsonObject

LOGGER = logging.getLogger("service-monitoring")


def access_percent(stats: NginxAccessWindowStats | None) -> float | None:
    """Calculate the 502/504 percentage for one bounded access-log window.

    Returns:
        The percentage, or ``None`` when no requests were observed.
    """
    if stats is None or stats.total <= 0:
        return None
    return stats.status_502_504 / stats.total * 100.0


def collect_header_issues(
    ctx: MonitorContext, cycle: DomainCycle,
) -> list[ProxyIssue]:
    """Collect header issues routed by active inventory alert policy.

    Returns:
        Alertable upstream-header issues.
    """
    all_issues = check_upstream_header_expectations(
        specs_by_domain=ctx.settings.inventory.specs_by_domain,
        cycle_results=cycle.results,
    )
    alertable = ctx.alertable_domains
    issues = [issue for issue in all_issues if issue.domain in alertable]
    suppressed_issues = [issue for issue in all_issues if issue.domain not in alertable]
    suppressed = {issue.domain for issue in suppressed_issues}
    if suppressed:
        LOGGER.info(
            "Proxy header failures excluded from Telegram routing domains=%s",
            sorted(suppressed),
        )
    return issues


def collect_access_observation(
    options: JsonObject, window_seconds: int,
) -> tuple[NginxAccessWindowStats | None, float | None, bool]:
    """Read bounded access-log evidence and evaluate its configured threshold.

    Returns:
        Window statistics, error percentage, and threshold result.
    """
    path = str(options.get("access_log_path") or "/var/log/nginx/access.log").strip()
    maximum = optional_float(options.get("max_502_504_percent"))
    stats = None
    if maximum is not None and path:
        stats = compute_access_window_stats(
            access_log_path=path,
            now=datetime.now(UTC),
            window_seconds=window_seconds,
            max_bytes=max(
                10_000,
                int_value(options.get("access_log_max_bytes"), default=1_000_000),
            ),
        )
    percentage = access_percent(stats)
    minimum = max(0, int_value(options.get("min_total_requests"), default=50))
    violated = bool(
        stats is not None
        and stats.total >= minimum
        and percentage is not None
        and maximum is not None
        and percentage > maximum,
    )
    return stats, percentage, violated


def _routed_events(
    ctx: MonitorContext,
    events: list[NginxUpstreamErrorEvent],
) -> list[NginxUpstreamErrorEvent]:
    inventory_domains = ctx.settings.inventory.entries_by_domain
    external = [event for event in events if event.server not in inventory_domains]
    inventory = [event for event in events if event.server in inventory_domains]
    alertable = ctx.alertable_domains
    routed_inventory = [event for event in inventory if event.server in alertable]
    return [*external, *routed_inventory]


def upstream_violation(
    ctx: MonitorContext,
    cycle: DomainCycle,
    summary: NginxUpstreamSummary | None,
    options: JsonObject,
) -> bool:
    """Evaluate routed per-domain upstream counts against policy.

    Returns:
        Whether any alertable domain crossed the threshold.
    """
    threshold = max(
        0,
        int_value(options.get("max_upstream_errors_per_domain"), default=5),
    )
    if summary is None or threshold <= 0:
        return False
    alertable = ctx.alertable_domains
    alertable_specs = [spec for spec in cycle.enabled_specs if spec.domain in alertable]
    enabled_domains = {spec.domain for spec in alertable_specs}
    return any(
        server in enabled_domains and count >= threshold
        for server, count in summary["counts_by_server"].items()
    )


def collect_upstream_observation(
    ctx: MonitorContext,
    options: JsonObject,
    window_seconds: int,
) -> tuple[list[NginxUpstreamErrorEvent], NginxUpstreamSummary | None]:
    """Read and route bounded Nginx upstream-error evidence.

    Returns:
        Routed events and their optional summary.
    """
    path = str(options.get("error_log_path") or "/var/log/nginx/error.log").strip()
    threshold = max(
        0,
        int_value(options.get("max_upstream_errors_per_domain"), default=5),
    )
    if not path or threshold <= 0:
        return [], None
    parsed = parse_recent_upstream_errors(
        error_log_path=path,
        now=datetime.now(UTC),
        window_seconds=window_seconds,
        local_tz=load_timezone(str(options.get("timezone") or "Europe/Amsterdam")),
        max_bytes=max(
            10_000,
            int_value(options.get("error_log_max_bytes"), default=1_000_000),
        ),
    )
    events = _routed_events(ctx, parsed)
    return events, summarize_upstream_errors(events) if events else None
