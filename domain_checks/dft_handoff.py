# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded candidate reads keep shared authority until a verified handoff."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from .dft_access_cutover import DftAccessCutover
from .dft_access_segments import read_production_window

if TYPE_CHECKING:
    from pathlib import Path

    from .dft_cutover_config import CutoverBoundary
    from .dft_journal import DftJournal

_MINIMUM_WINDOW_SECONDS = 300


@dataclass(frozen=True)
class CandidateWindow:
    """The next checker observation consumes this cycle's bounded read intent."""

    seconds: int
    max_bytes: int


class DftHandoff:
    """Persist selection separately from requests; never auto-fallback after it."""

    def __init__(
        self, mode: Literal["shared", "segments"], boundary: CutoverBoundary | None,
        journal: DftJournal, root: Path,
    ) -> None:
        """Restore only the matching original admission's selected source.

        Raises:
            ValueError: A segment request has no boundary or changes active admission.
        """
        active = journal.active_segment_boundary()
        if mode == "segments" and (boundary is None or (active is not None and active != boundary)):
            message = "dft_cutover_boundary_missing_or_changed"
            raise ValueError(message)
        self.requested_mode: Literal["shared", "segments"] = mode
        self.boundary: CutoverBoundary | None = boundary
        self.journal: DftJournal = journal
        self.access: DftAccessCutover = DftAccessCutover(
            "segments" if mode == "segments" and active is not None else "shared", root,
        )
        self.access.snapshots = journal.load_segments()
        self.window: CandidateWindow | None = None

    @property
    def pending(self) -> bool:
        """Report incomplete selection without claiming a new source is healthy."""
        return self.requested_mode == "segments" and self.access.mode == "shared"

    def record_read(self, *, now: float, covered: bool, window_seconds: int, max_bytes: int) -> None:
        """Prepare one bounded candidate read; explicit shared rollback retires selection."""
        self.window = CandidateWindow(window_seconds, max_bytes) if covered and self.pending else None
        if covered and self.requested_mode == "shared":
            self.journal.retire_segment_selection(now=now)

    def observe(self, *, now: float, checker_healthy: bool) -> None:
        """Catch up within this cycle and persist authority only after actual proof."""
        window, self.window = self.window, None
        boundary = self.boundary
        if not self.pending or window is None or boundary is None:
            return
        if window.seconds < _MINIMUM_WINDOW_SECONDS or now - window.seconds < max(
            boundary.writer_adopted_at, boundary.old_workers_drained_at,
        ):
            return
        ready = False
        with suppress(OSError, ValueError):
            _ = read_production_window(self.access.production_root, now=datetime.fromtimestamp(now, UTC),
                                       window_seconds=window.seconds, max_bytes=window.max_bytes,
                                       snapshots=self.access.snapshots)
            ready = True
        self.journal.save_segments(self.access.snapshots)
        if ready and checker_healthy:
            self.journal.select_segments(boundary, now=now)
            self.access.mode = "segments"
