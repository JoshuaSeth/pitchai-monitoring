# Copyright (c) 2026 PitchAI. All rights reserved.
"""Cycle-owned signal rows with original append identity and prefix pruning."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .cycle_values import required_float

if TYPE_CHECKING:
    from .history_decode import Sample


def _row_timestamp(sample: Sample) -> float | None:
    if sample:
        with suppress(TypeError, ValueError, OverflowError):
            return required_float(sample[0])
    return None


@dataclass
class SignalHistory:
    """Operate on the existing mutable map without owning persistence or delivery."""

    samples: dict[str, list[Sample]]

    def append(self, name: str, sample: Sample) -> None:
        """Append the same row object; empty names and rows remain omitted."""
        key = str(name or "").strip()
        if not key or not sample:
            return
        items = self.samples.get(key)
        if items is None:
            self.samples[key] = [sample]
            return
        items.append(sample)

    def prune(self, *, before_ts: float) -> None:
        """Drop the prefix before the first qualifying row, retaining equal ages."""
        cutoff = float(before_ts)
        for key in list(self.samples):
            items = self.samples.get(key) or []
            if not items:
                self.samples.pop(key, None)
                continue
            index = len(items)
            for position, sample in enumerate(items):
                timestamp = _row_timestamp(sample)
                if timestamp is not None and timestamp >= cutoff:
                    index = position
                    break
            if index <= 0:
                continue
            if index >= len(items):
                self.samples.pop(key, None)
                continue
            del items[:index]
            self.samples[key] = items
