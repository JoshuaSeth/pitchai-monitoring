# Copyright (c) 2026 PitchAI. All rights reserved.
"""Inventory selection and concurrent domain polling for one native cycle."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .browser_admission import BrowserConnection
from .cycle_history import record_domain_results
from .domain_entries import format_disabled_domain_line
from .history import prune_history
from .history_phase_context import HistoryComputeBoundary

if TYPE_CHECKING:
    from datetime import tzinfo

    from .browser_admission import BrowserAdmission
    from .common_check import DomainCheckResult, DomainCheckSpec
    from .cycle_persistence import CyclePersistence
    from .domain_entries import DomainEntryConfig
    from .domain_polling import DomainPolling
    from .domain_result_phase import DomainResultPhase


@dataclass(frozen=True)
class CycleInventory:
    """The configured entries/specs and display timezone, without new discovery."""

    entries: list[DomainEntryConfig]
    specs: dict[str, DomainCheckSpec]
    timezone: tzinfo | None


@dataclass
class DomainCycleObservation:
    """Current results and selected domains, shared with subsequent phases."""

    results: dict[str, DomainCheckResult]
    specs: list[DomainCheckSpec]
    disabled_lines: list[str]
    browser_degraded: bool = False


@dataclass(frozen=True)
class CycleDomainPhase[BrowserT: BrowserConnection]:
    """Keep poll ordering, per-domain stops and history updates at their original edges."""

    inventory: CycleInventory
    persistence: CyclePersistence
    browser: BrowserAdmission[BrowserT]
    polling: DomainPolling[BrowserT]
    result_phase: DomainResultPhase
    retention_seconds: float

    def _select(self, now: float) -> DomainCycleObservation:
        """Clear only disabled domain counters and retain configured iteration order.

        Returns:
            The original sorted disabled lines and enabled spec references.
        """
        disabled = [entry for entry in self.inventory.entries if entry.is_disabled(now)]
        names = {entry.domain for entry in disabled}
        records, health = self.persistence.records, self.persistence.health
        for domain in names:
            records.domains.last_ok.pop(domain, None)
            records.domains.fail_streak.pop(domain, None)
            records.domains.success_streak.pop(domain, None)
            records.history.pop(domain, None)
            for name in ("synthetic", "web_vitals", "api_contract"):
                probe = health.probes[name]
                probe.last_ok.pop(domain, None)
                probe.fail_streak.pop(domain, None)
                probe.success_streak.pop(domain, None)
                probe.last_run_ts.pop(domain, None)
            health.dns_ips.pop(domain, None)
        lines = sorted(format_disabled_domain_line(entry, self.inventory.timezone) for entry in disabled)
        enabled = [entry for entry in self.inventory.entries if entry.domain not in names]
        specs = [self.inventory.specs[entry.domain] for entry in enabled]
        return DomainCycleObservation({}, specs, lines)

    async def run(self, started: float) -> DomainCycleObservation:
        """Reuse browser admission before choosing domains, then consume completed checks.

        A cancelled or failed result leaves sibling tasks under their existing
        event-loop ownership. This phase introduces no blanket task cleanup.

        Returns:
            The completed observation, retaining result and spec identity.
        """
        await self.browser.ensure(time.time())
        observation = self._select(time.time())
        tasks = [asyncio.create_task(self.polling.run(spec)) for spec in observation.specs]
        for future in asyncio.as_completed(tasks):
            result = await future
            observation.results[result.domain] = result
            if bool((result.details or {}).get("browser_infra_error")):
                observation.browser_degraded = True
            await self.result_phase.observe(result, started)
        records = self.persistence.records
        # CycleRecords normalizes history to this mutable dictionary at startup;
        # later phases mutate entries, never replace it with another type.
        record_domain_results(records.history, observation.results, records.domains.last_ok, ts=started)
        with HistoryComputeBoundary("Failed to prune history"):
            prune_history(records.history, before_ts=time.time() - float(self.retention_seconds))
        return observation
