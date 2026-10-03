# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native Docker list/inspect scheduling and existing health classification."""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NotRequired, TypedDict, Unpack, cast

from .container_health_records import ContainerHealthIssue, assess_container
from .docker_unix import docker_unix_get_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from .event_bus_delivery import JsonValue

__all__ = ["ContainerHealthIssue", "check_container_health"]


def _compile_patterns(items: Sequence[str]) -> list[re.Pattern[str]]:
    if not isinstance(items, list):
        return []
    patterns: list[re.Pattern[str]] = []
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        # Regex configuration keeps its existing invalid-pattern literal fallback.
        with suppress(re.error):
            patterns.append(re.compile(value))
            continue
        patterns.append(re.compile(re.escape(value)))
    return patterns


def _matches_any(name: str, patterns: list[re.Pattern[str]]) -> bool:
    for pattern in patterns:
        # Preserve the existing per-pattern ordinary-error fallback.
        with suppress(Exception):
            if pattern.search(name):
                return True
    return False


class InspectionTuning(TypedDict):
    """The two existing optional keyword arguments and their native defaults."""

    timeout_seconds: NotRequired[float]
    concurrency: NotRequired[int]


def _validate_tuning(tuning: InspectionTuning) -> None:
    for key in tuning:
        if key not in {"timeout_seconds", "concurrency"}:
            message = f"check_container_health() got an unexpected keyword argument '{key}'"
            raise TypeError(message)


@dataclass
class ContainerInspector:
    """Own this observation's admitted inspections and newly available counts."""

    socket_path: str
    timeout_seconds: float
    semaphore: asyncio.Semaphore
    previous: dict[str, int]
    counts: dict[str, int] = field(default_factory=dict)

    def schedule(
        self, selected: Iterable[tuple[str, str, str | None]],
    ) -> list[asyncio.Task[ContainerHealthIssue | None]]:
        """Create inspection tasks before awaiting any completion.

        Returns:
            Tasks in listing order under this observation's semaphore ownership.
        """
        tasks: list[asyncio.Task[ContainerHealthIssue | None]] = []
        for container_id, name, status in selected:
            tasks.append(asyncio.create_task(self.read(container_id, name, status)))
        return tasks

    async def read(self, container_id: str, name: str, status: str | None) -> ContainerHealthIssue | None:
        """Return an issue after one admitted native read, keeping missing fields unknown."""
        async with self.semaphore:
            inspected = await asyncio.to_thread(
                docker_unix_get_json, socket_path=self.socket_path, path=f"/containers/{container_id}/json",
                timeout_seconds=float(self.timeout_seconds),
            )
        inspected_data = cast("JsonValue", inspected.data)
        if not inspected.ok or not isinstance(inspected_data, dict):
            return ContainerHealthIssue.unavailable(
                name=name, container_id=container_id[:12], status=status,
                error=f"docker_inspect_failed: {inspected.error or inspected.status}",
            )
        issue, count = assess_container(name=name, container_id=container_id, status=status,
                                        data=inspected_data, previous_count=self.previous.get(container_id))
        if count is not None:
            self.counts[container_id] = count
        return issue


def _selected(
    listed_data: list[JsonValue], included: list[re.Pattern[str]], excluded: list[re.Pattern[str]], *,
    monitor_all: bool,
) -> Iterator[tuple[str, str, str | None]]:
    for entry in listed_data:
        if not isinstance(entry, dict):
            continue
        container_id = str(entry.get("Id") or "").strip()
        if not container_id:
            continue
        names = entry.get("Names")
        name = str(names[0] or "").lstrip("/") if isinstance(names, list) and names else ""
        if not name:
            name = container_id[:12]
        status = str(entry.get("Status") or "").strip() or None
        if _matches_any(name, excluded):
            continue
        if not monitor_all and (not included or not _matches_any(name, included)):
            continue
        yield container_id, name, status


async def check_container_health(
    *, docker_socket_path: str, include_name_patterns: list[str] | None, exclude_name_patterns: list[str] | None,
    monitor_all: bool, previous_restart_counts: dict[str, int] | None, **tuning: Unpack[InspectionTuning],
) -> tuple[list[ContainerHealthIssue], dict[str, int]]:
    """List and inspect selected containers through the unchanged native client.

    Returns:
        Sorted issues and available restart counts. Failed observations stay
        unknown; worker cancellation and task ownership retain their old boundary.
    """
    _validate_tuning(tuning)
    included = _compile_patterns(include_name_patterns or [])
    excluded = _compile_patterns(exclude_name_patterns or [])
    listing = await asyncio.to_thread(
        docker_unix_get_json, socket_path=docker_socket_path, path="/containers/json?all=1",
        timeout_seconds=float(tuning.get("timeout_seconds", 3.0)),
    )
    listed_data = cast("JsonValue", listing.data)
    if not listing.ok or not isinstance(listed_data, list):
        issue = ContainerHealthIssue.unavailable(name="docker", container_id="", status=None,
                                                error=f"docker_list_failed: {listing.error or listing.status}")
        return [issue], {}
    inspector = ContainerInspector(docker_socket_path, tuning.get("timeout_seconds", 3.0),
        asyncio.Semaphore(max(1, int(tuning.get("concurrency", 8)))),
        previous_restart_counts if isinstance(previous_restart_counts, dict) else {})
    tasks = inspector.schedule(_selected(listed_data, included, excluded, monitor_all=monitor_all))

    issues: list[ContainerHealthIssue] = []
    for future in asyncio.as_completed(tasks):
        issue = await future
        if issue is not None:
            issues.append(issue)
    issues.sort(key=lambda item: item.name)
    return issues, inspector.counts
