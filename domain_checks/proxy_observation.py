# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read the configured proxy feeds through the existing DFT access authority."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .domain_time import load_timezone
from .metrics_nginx import parse_recent_upstream_errors, summarize_upstream_errors
from .metrics_proxy import check_upstream_header_expectations

if TYPE_CHECKING:
    from .common_check import DomainCheckResult, DomainCheckSpec
    from .dft_cycle import DftCycle
    from .event_bus_delivery import JsonObject
    from .metrics_nginx import NginxAccessWindowStats, NginxUpstreamErrorEvent
    from .metrics_proxy import ProxyIssue
    from .probe_frame import ProbeDomains
    from .proxy_settings import ProxySettings

LOGGER = logging.getLogger("service-monitoring")


@dataclass
class ProxyObservation:
    """One read's existing counters and evidence, without making source selection."""

    issues: list[ProxyIssue]
    access: NginxAccessWindowStats | None = None
    access_violation: bool = False
    upstream: list[NginxUpstreamErrorEvent] = field(default_factory=list)
    summary: JsonObject | None = None
    upstream_violation: bool = False

    def counters(self) -> tuple[float | None, int, int]:
        """Preserve the original all-or-empty diagnostic conversion fallback.

        Returns:
            502/504 percentage, total and 502/504 request counts.
        """
        if self.access is not None:
            # This diagnostic fallback cannot change the observation/health.
            with suppress(Exception):
                total = int(self.access.total)
                bad = int(self.access.status_502_504)
                return (bad / float(total or 1)) * 100.0, total, bad
        return None, 0, 0


@dataclass(frozen=True)
class ProxyReader:
    """Keep the DFT cycle as the sole access-feed/cursor owner."""

    settings: ProxySettings
    dft: DftCycle
    specs: dict[str, DomainCheckSpec]

    def read(self, domains: ProbeDomains, results: dict[str, DomainCheckResult]) -> ProxyObservation:
        """Read header/access/error observations in their original order.

        Returns:
            The same routed issues, global access counters and upstream summary.
        """
        local_tz = load_timezone(self.settings.feed.timezone_name)
        all_issues = check_upstream_header_expectations(specs_by_domain=self.specs, cycle_results=results)
        muted_issues = [item for item in all_issues if item.domain not in domains.alertable]
        muted = [item.domain for item in muted_issues]
        suppressed = sorted(set(muted))
        if suppressed:
            LOGGER.info("Proxy header failures excluded from Telegram routing domains=%s", suppressed)
        observation = ProxyObservation([item for item in all_issues if item.domain in domains.alertable])
        self._access(observation)
        if self.settings.feed.error_log_path and self.settings.max_upstream_errors_per_domain > 0:
            all_events = parse_recent_upstream_errors(
                error_log_path=self.settings.feed.error_log_path, now=datetime.now(UTC),
                window_seconds=int(self.settings.feed.window_seconds), local_tz=local_tz,
                max_bytes=int(self.settings.feed.error_max_bytes),
            )
            excluded = domains.known - domains.alertable
            observation.upstream = [event for event in all_events if event.server not in excluded]
            summary = summarize_upstream_errors(observation.upstream)
            observation.summary = {
                "counts_by_server": dict(summary["counts_by_server"]),
                "raw_counts_by_server": dict(summary["raw_counts_by_server"]),
                "duplicate_counts_by_server": dict(summary["duplicate_counts_by_server"]),
                "samples_by_server": {key: list(value) for key, value in summary["samples_by_server"].items()},
                "request_event_count": summary["request_event_count"], "raw_event_count": summary["raw_event_count"],
            }
            configured = {spec.domain for spec in domains.specs}
            enabled = configured & domains.alertable
            counts = summary["counts_by_server"]
            observation.upstream_violation = any(
                int(count) >= int(self.settings.max_upstream_errors_per_domain)
                for server, count in counts.items() if server in enabled
            )
        return observation

    def _access(self, observation: ProxyObservation) -> None:
        """Retain DFT coverage faults and the existing strict rate threshold."""
        if self.settings.max_502_504_percent is None or not self.settings.feed.access_log_path:
            return
        observation.access = self.dft.read_access(
            access_log_path=self.settings.feed.access_log_path, now=datetime.now(UTC),
            window_seconds=int(self.settings.feed.window_seconds), max_bytes=int(self.settings.feed.access_max_bytes),
        )
        access = observation.access
        if access is not None and access.total >= int(self.settings.min_total_requests):
            percent = (int(access.status_502_504) / float(access.total or 1)) * 100.0
            if float(percent) > float(self.settings.max_502_504_percent):
                observation.access_violation = True
