# Copyright (c) 2026 PitchAI. All rights reserved.
"""One-time observed-to-effective conversion for retained domain history."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .alert_transition import update_effective_ok

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonValue
    from .history_decode import Sample

_MIN_FIELDS = 2


def _effective_samples(items: list[JsonValue], *, down: int, up: int) -> list[Sample]:
    effective, failures, successes = True, 0, 0
    result: list[Sample] = []
    for sample in items:
        if not isinstance(sample, list) or len(sample) < _MIN_FIELDS:
            continue
        effective, failures, successes, _alerted = update_effective_ok(
            prev_effective_ok=bool(effective), observed_ok=bool(sample[1]),
            fail_streak=int(failures), success_streak=int(successes),
            down_after_failures=down, up_after_successes=up,
        )
        copied = list(sample)
        copied[1] = bool(effective)
        result.append(copied)
    return result


def migrate_effective_history(
    history: Mapping[str, JsonValue], *, down_after_failures: int, up_after_successes: int,
) -> dict[str, list[Sample]]:
    """Build debounced rows independently per domain without mutating input rows.

    Returns:
        Nonempty domain histories with original order, timestamps and extra fields.
    """
    migrated: dict[str, list[Sample]] = {}
    for domain, items in history.items():
        if not domain or not isinstance(items, list) or not items:
            continue
        rows = _effective_samples(items, down=down_after_failures, up=up_after_successes)
        if rows:
            migrated[domain] = rows
    return migrated
