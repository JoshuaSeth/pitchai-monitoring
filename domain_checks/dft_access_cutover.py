# Copyright (c) 2026 PitchAI. All rights reserved.
"""Select exactly one production DFT feed while preserving all other hosts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .dft_access_segments import read_production_window
from .metrics_nginx import AccessHostPolicy, NginxAccessWindowStats, compute_access_window_stats

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from .dft_segment_io import SegmentSnapshot

DFT_PRODUCTION = "formatief-toetsen.pitchai.net"
DFT_STAGING = "staging.formatief-toetsen.pitchai.net"


@dataclass
class DftAccessCutover:
    """The admitted selection controls both DFT shared exclusion and segment use."""

    mode: Literal["shared", "segments"]
    production_root: Path
    snapshots: dict[str, SegmentSnapshot] = field(default_factory=dict)

    def read(
        self, *, access_log_path: str, now: datetime, window_seconds: int,
        max_bytes: int = 1_000_000,
    ) -> NginxAccessWindowStats | None:
        """Read the unchanged shared feed plus the selected production source.

        Shared mode never opens the proposed segment root. Segment mode never
        falls back to shared DFT records after a coverage failure. Empty shared
        input cannot prove unrelated-host coverage, so it stays unavailable.

        Returns:
            Counts without DFT raw samples, or None if the shared feed is unreadable.
        """
        excluded = frozenset({DFT_STAGING, DFT_PRODUCTION} if self.mode == "segments" else {DFT_STAGING})
        shared = compute_access_window_stats(
            access_log_path=access_log_path, now=now, window_seconds=window_seconds, max_bytes=max_bytes,
            host_policy=AccessHostPolicy(excluded=excluded, redacted=frozenset({DFT_PRODUCTION}),
                                        require_attribution=True),
        )
        if self.mode == "shared" or shared is None:
            return shared
        segment = read_production_window(self.production_root, now=now, window_seconds=window_seconds,
                                         max_bytes=max_bytes, snapshots=self.snapshots)
        return NginxAccessWindowStats(
            shared.total + segment.total, shared.status_5xx + segment.status_5xx,
            shared.status_502_504 + segment.status_502_504, shared.status_4xx + segment.status_4xx,
            shared.sample_lines,
        )
