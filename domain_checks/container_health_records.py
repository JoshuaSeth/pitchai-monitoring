# Copyright (c) 2026 PitchAI. All rights reserved.
"""Docker inspection records with unknown observations kept distinct from health."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .container_status import ContainerStatus
from .cycle_values import required_int

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


@dataclass(frozen=True)
class ContainerHealthIssue(ContainerStatus):
    """The existing public inspection result and persisted diagnostic field names."""

    restart_count: int | None
    restart_increase: int | None
    oom_killed: bool | None
    health_status: str | None
    exit_code: int | None
    error: str | None

    @classmethod
    def unavailable(cls, *, name: str, container_id: str, status: str | None, error: str | None) -> Self:
        """Return a failed observation without inventing any inspected state."""
        return cls(name=name, container_id=container_id, running=None, status=status,
                   restart_count=None, restart_increase=None, oom_killed=None,
                   health_status=None, exit_code=None, error=error)


def _optional_integer(value: JsonValue) -> int | None:
    # The native JSON conversion previously retained None on ordinary failures.
    with suppress(Exception):
        if value is not None:
            return required_int(value)
    return None


def _optional_bool(value: JsonValue) -> bool | None:
    return value if isinstance(value, bool) else None


def _health_status(value: JsonValue) -> str | None:
    if isinstance(value, dict):
        status = value.get("Status")
        if isinstance(status, str) and status.strip():
            return status.strip()
    return None


def assess_container(
    *, name: str, container_id: str, status: str | None, data: JsonObject, previous_count: int | None,
) -> tuple[ContainerHealthIssue | None, int | None]:
    """Classify the existing Docker JSON without changing the caller's restart map.

    Returns:
        An issue when currently unhealthy and the available restart count, even
        for healthy containers. Historical OOM alone remains non-alerting.
    """
    raw_state = data.get("State")
    state = raw_state if isinstance(raw_state, dict) else {}
    running = _optional_bool(state.get("Running"))
    oom = _optional_bool(state.get("OOMKilled"))
    exit_code = _optional_integer(state.get("ExitCode"))
    health_status = _health_status(state.get("Health"))
    restart_count = _optional_integer(data.get("RestartCount"))
    restart_increase = None
    if restart_count is not None and previous_count is not None:
        with suppress(Exception):
            delta = restart_count - required_int(previous_count)
            if delta != 0:
                restart_increase = delta
    bad = (running is False or (bool(health_status) and health_status != "healthy")
           or (restart_increase is not None and restart_increase > 0))
    if not bad:
        return None, restart_count
    return ContainerHealthIssue(name=name, container_id=container_id[:12], running=running, status=status,
                                restart_count=restart_count, restart_increase=restart_increase, oom_killed=oom,
                                health_status=health_status, exit_code=exit_code, error=None), restart_count
