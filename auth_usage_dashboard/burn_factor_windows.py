# Copyright (c) 2026 PitchAI. All rights reserved.
"""Rolling-window and horizon request parsing for the burn factor (``30m:24h,24h:6d``)."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_PAIRS = "30m:24h,24h:6d"
MAX_PAIRS = 6
ROLLING_LIMITS = (5 * 60, 7 * 86_400)
HORIZON_LIMITS = (3_600, 14 * 86_400)
_DURATION = re.compile(r"^(\d{1,5})([mhd])$")
_UNIT_SECONDS = {"m": 60, "h": 3_600, "d": 86_400}
_PAIR_PARTS = 2


@dataclass(frozen=True)
class WindowPair:
    """One requested rolling window and future horizon, in seconds and as typed."""

    rolling: str
    rolling_seconds: int
    horizon: str
    horizon_seconds: int


def parse_duration(text: str, limits: tuple[int, int]) -> int:
    """Return seconds for ``<n>m``, ``<n>h`` or ``<n>d`` within ``limits``.

    Raises:
        ValueError: For an unparsable or out-of-range duration.
    """
    match = _DURATION.match(text.strip().lower())
    seconds = int(match.group(1)) * _UNIT_SECONDS[match.group(2)] if match else 0
    if not limits[0] <= seconds <= limits[1]:
        message = f"duration {text!r} must look like 30m, 6h or 2d and lie within {limits[0]}..{limits[1]} seconds"
        raise ValueError(message)
    return seconds


def parse_pairs(raw: str) -> list[WindowPair]:
    """Return 1-6 ``rolling:horizon`` pairs from a comma-separated request value.

    Raises:
        ValueError: For a malformed pair list.
    """
    pairs: list[WindowPair] = []
    for item in (part.strip() for part in raw.split(",") if part.strip()):
        parts = item.split(":")
        if len(parts) != _PAIR_PARTS:
            message = f"pair {item!r} must look like rolling:horizon, e.g. 30m:24h"
            raise ValueError(message)
        rolling, horizon = parts[0].strip(), parts[1].strip()
        rolling_seconds = parse_duration(rolling, ROLLING_LIMITS)
        pairs.append(WindowPair(rolling, rolling_seconds, horizon, parse_duration(horizon, HORIZON_LIMITS)))
    if not 1 <= len(pairs) <= MAX_PAIRS:
        message = f"request between 1 and {MAX_PAIRS} rolling:horizon pairs"
        raise ValueError(message)
    return pairs
