# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated cold selection, original-window admission and restart behavior."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from .dft_access_cutover import DFT_PRODUCTION
from .dft_cutover_config import CutoverBoundary, parse_cutover_boundary
from .dft_cycle import DftCycle, DftCycleConfig
from .dft_retention_consumer import CheckerObservation
from .dft_test_support import require, require_error
from .test_dft_cutover import shared_line

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue
    from .metrics_nginx import NginxAccessWindowStats

_NOW = datetime(2026, 10, 2, 12, 10, tzinfo=UTC)
_BUDGET = 1000
_SELECTED_TOTAL = 2


@dataclass
class HandoffFixture:
    """All paths and records belong to a temporary synthetic allocation."""

    root: Path

    @property
    def config(self) -> DftCycleConfig:
        """Supply earlier owner-proved adoption times for the isolated example."""
        return DftCycleConfig("segments", self.root, self.root / "config", self.root / "consumer.sqlite",
                              cutover=CutoverBoundary(_NOW.timestamp() - 600, _NOW.timestamp() - 400))

    @property
    def segment(self) -> Path:
        """Locate the sole original synthetic hour without resolving another root."""
        return self.root / "production" / "dft-access-2026-10-02T12+00:00.jsonl"

    def prepare(self, *, old_records: int = 0) -> None:
        """Create deliberately different source counts to expose premature selection."""
        self.segment.parent.mkdir()
        row = {"class": "dft-web-access-v1", "capture_hour": "2026-10-02T12+00:00",
               "event_unix": _NOW.timestamp() - 500, "status": 200, "agent": "synthetic-private"}
        old = json.dumps(row) + "\n"
        row["event_unix"] = _NOW.timestamp()
        self.segment.write_text(old * old_records + json.dumps(row) + "\n", encoding="utf-8")
        (self.root / "shared").write_text(shared_line(DFT_PRODUCTION, _NOW, 502)
                                         + shared_line("other.pitchai.net", _NOW, 404), encoding="utf-8")

    def cycle(self, config: DftCycleConfig | None = None) -> DftCycle:
        """Bind only the synthetic production path; no host source is opened.

        Returns:
            An enabled local consumer with no receiver.
        """
        with patch("domain_checks.dft_cycle._PRODUCTION_ROOT", self.segment.parent):
            return DftCycle(self.config if config is None else config)

    def read(self, cycle: DftCycle, *, now: datetime = _NOW) -> NginxAccessWindowStats | None:
        """Supply a real shared read to this poll before observing its checker.

        Returns:
            The actual selected source's counters for comparison.
        """
        return cycle.read_access(access_log_path=str(self.root / "shared"), now=now,
                                 window_seconds=300, max_bytes=_BUDGET)


class TestDftHandoff(unittest.IsolatedAsyncioTestCase):
    """No live checker, nginx process, event or outgoing transport is invoked."""

    @staticmethod
    async def test_catchup_and_checker_before_selection_then_no_fallback() -> None:
        """Keep shared counts through catch-up/restart/failure; never fallback after selection."""
        with tempfile.TemporaryDirectory() as directory:
            fixture = HandoffFixture(Path(directory))
            fixture.prepare(old_records=7)
            cycle = fixture.cycle()
            shared = fixture.read(cycle)
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await cycle.observe(now=_NOW.timestamp())
            require(condition=cycle.summary.get("active_access_source") == "shared",
                    message="incomplete cold parse selected segments")
            incident_id = cycle.summary.get("incident_id")
            cycle.close()
            cycle = fixture.cycle()
            require(condition=fixture.read(cycle) == shared, message="restart lost shared authority")
            with patch("domain_checks.dft_cycle.observe_checker",
                       return_value=CheckerObservation(errors=("retention_fault_latched",))):
                await cycle.observe(now=_NOW.timestamp())
            require(condition=cycle.summary.get("active_access_source") == "shared",
                    message="complete parse with failed checker selected segments")
            _ = fixture.read(cycle)
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await cycle.observe(now=_NOW.timestamp())
            require(condition=cycle.summary.get("active_access_source") == "segments",
                    message="complete original window plus healthy checker did not select segments")
            require(condition=incident_id is not None and cycle.summary.get("incident_id") == incident_id
                    and cycle.summary.get("incident_closed_at") is None,
                    message="source selection closed or replaced an unacknowledged incident")
            cycle.close()
            cycle = fixture.cycle()
            selected = fixture.read(cycle)
            require(condition=selected is not None and selected.total == _SELECTED_TOTAL
                    and selected.status_502_504 == 0,
                    message="persisted selection duplicated or used old DFT traffic")
            fixture.segment.unlink()
            require(condition=fixture.read(cycle) is None, message="missing selected segments fell back to shared")
            cycle.close()

    @staticmethod
    async def test_original_drain_time_and_fresh_read_are_required() -> None:
        """An empty pre-created hour or elapsed writer age cannot prove old-worker drain."""
        with tempfile.TemporaryDirectory() as directory:
            fixture = HandoffFixture(Path(directory))
            fixture.prepare()
            fixture.segment.write_bytes(b"")
            boundary = CutoverBoundary(_NOW.timestamp() - 600, _NOW.timestamp() - 299)
            cycle = fixture.cycle(replace(fixture.config, cutover=boundary))
            _ = fixture.read(cycle)
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await cycle.observe(now=_NOW.timestamp())
                await cycle.observe(now=_NOW.timestamp() + 60)
            require(condition=cycle.summary.get("active_access_source") == "shared",
                    message="pre-drain interval or skipped read selected empty hours")
            _ = fixture.read(cycle, now=datetime.fromtimestamp(_NOW.timestamp() + 60, UTC))
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await cycle.observe(now=_NOW.timestamp() + 60)
            require(condition=cycle.summary.get("active_access_source") == "segments",
                    message="a complete admitted quiet interval could not be selected")
            cycle.close()

    @staticmethod
    async def test_changed_active_boundary_refused_and_explicit_rollback_retains_history() -> None:
        """Restart cannot reset admission times; explicit shared rollback retains original history."""
        with tempfile.TemporaryDirectory() as directory:
            fixture = HandoffFixture(Path(directory))
            fixture.prepare()
            cycle = fixture.cycle()
            _ = fixture.read(cycle)
            with patch("domain_checks.dft_cycle.observe_checker", return_value=CheckerObservation(age_seconds=1)):
                await cycle.observe(now=_NOW.timestamp())
            cycle.close()
            changed = replace(fixture.config, cutover=CutoverBoundary(_NOW.timestamp(), _NOW.timestamp()))
            with require_error(ValueError, "dft_cutover_boundary_missing_or_changed"):
                fixture.cycle(changed)
            shared = fixture.cycle(replace(fixture.config, mode="shared"))
            _ = fixture.read(shared)
            if shared.journal is not None:
                rows = cast("list[tuple[float, float, float, float]]",
                            shared.journal.connection.execute("SELECT * FROM source_selections").fetchall())
                require(condition=rows == [(_NOW.timestamp() - 600, _NOW.timestamp() - 400,
                                             _NOW.timestamp(), _NOW.timestamp())],
                        message="explicit rollback erased or rewrote original selection history")
            shared.close()
            pending = fixture.cycle(changed)
            require(condition=pending.access is not None and pending.access.mode == "shared",
                    message="new admission bypassed preparation after explicit rollback")
            pending.close()

    @staticmethod
    async def test_invalid_admission_times_are_rejected() -> None:
        """Missing, boolean and invalid original times never authorize a source switch."""
        invalid: list[JsonValue] = [None, {}, {"writer_adopted_at": True, "old_workers_drained_at": 1},
                                    {"writer_adopted_at": 1, "old_workers_drained_at": float("inf")}]
        for value in invalid:
            with require_error(ValueError, "dft_invalid_cutover_boundary"):
                parse_cutover_boundary(value)
