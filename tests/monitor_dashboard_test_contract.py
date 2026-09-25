# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict output-shape validators for monitoring dashboard tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorRecord, MonitorValue


def require_monitor_record(value: MonitorValue, *, label: str) -> MonitorRecord:
    """Return a monitor record or fail the test's shape contract.

    Returns:
        The validated monitor record.

    Raises:
        TypeError: If the value is not a record.
    """
    if not isinstance(value, dict):
        message = f"{label} must be a monitor record"
        raise TypeError(message)
    return cast("MonitorRecord", value)


def require_monitor_records(value: MonitorValue, *, label: str) -> list[MonitorRecord]:
    """Return a list containing only monitor records.

    Returns:
        The validated monitor records.

    Raises:
        TypeError: If the value is not a list of records.
    """
    if not isinstance(value, list):
        message = f"{label} must be a list"
        raise TypeError(message)
    return [
        require_monitor_record(item, label=f"{label} item")
        for item in value
    ]


def require_monitor_float(value: MonitorValue, *, label: str) -> float:
    """Return a concrete floating-point monitor value.

    Returns:
        The validated floating-point value.

    Raises:
        TypeError: If the value is not numeric.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        message = f"{label} must be numeric"
        raise TypeError(message)
    return float(value)
