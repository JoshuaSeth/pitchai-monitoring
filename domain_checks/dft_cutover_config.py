# Copyright (c) 2026 PitchAI. All rights reserved.
"""Original admission times for the existing-cycle DFT source handoff."""

from __future__ import annotations

from dataclasses import dataclass
from sys import float_info
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue


@dataclass(frozen=True)
class CutoverBoundary:
    """Owner-proved times, never inferred from filenames or process restarts."""

    writer_adopted_at: float
    old_workers_drained_at: float

    def __post_init__(self) -> None:
        """Reject missing, boolean, non-finite and non-positive admission times.

        Raises:
            ValueError: Either original admission time is invalid.
        """
        values = (self.writer_adopted_at, self.old_workers_drained_at)
        if any(isinstance(value, bool) or not 0 < value <= float_info.max for value in values):
            message = "dft_invalid_cutover_boundary"
            raise ValueError(message)


def parse_cutover_boundary(value: JsonValue) -> CutoverBoundary:
    """Read the two explicit owner-proved timestamps for a requested handoff.

    Returns:
        The unchanged original writer-adoption and natural-drain times.

    Raises:
        ValueError: Either timestamp is missing or not numeric.
    """
    if isinstance(value, dict):
        writer, drained = value.get("writer_adopted_at"), value.get("old_workers_drained_at")
        if isinstance(writer, (int, float)) and isinstance(drained, (int, float)):
            return CutoverBoundary(writer, drained)
    message = "dft_invalid_cutover_boundary"
    raise ValueError(message)
