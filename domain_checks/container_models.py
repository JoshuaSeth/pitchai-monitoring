# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed state for Docker container-health checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict

if TYPE_CHECKING:
    import asyncio
    import re


class ContainerHealthIssue(NamedTuple):
    """Represent one unhealthy container or Docker boundary failure."""

    name: str
    container_id: str
    running: bool | None
    status: str | None
    restart_count: int | None
    restart_increase: int | None
    oom_killed: bool | None
    health_status: str | None
    exit_code: int | None
    error: str | None


class ContainerHealthOptions(TypedDict):
    """Keyword controls accepted by container-health inspection."""

    include_name_patterns: list[str] | None
    exclude_name_patterns: list[str] | None
    monitor_all: bool
    previous_restart_counts: dict[str, int] | None
    timeout_seconds: NotRequired[float]
    concurrency: NotRequired[int]


class ContainerJob(NamedTuple):
    """Identify one selected container inspection."""

    container_id: str
    name: str
    status: str | None


class ContainerState(NamedTuple):
    """Hold normalized fields from Docker's container state."""

    running: bool | None
    oom_killed: bool | None
    exit_code: int | None
    health_status: str | None
    restart_count: int | None


class ContainerScanContext(NamedTuple):
    """Hold immutable controls shared by container inspections."""

    socket_path: str
    timeout_seconds: float
    include_patterns: list[re.Pattern[str]]
    exclude_patterns: list[re.Pattern[str]]
    monitor_all: bool
    previous_counts: dict[str, int]
    semaphore: asyncio.Semaphore
