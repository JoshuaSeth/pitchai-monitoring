# Copyright (c) 2026 PitchAI. All rights reserved.
"""Docker container-health monitoring."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Unpack

from domain_checks.common_values import coerce_optional_int
from domain_checks.container_models import (
    ContainerHealthIssue,
    ContainerJob,
    ContainerScanContext,
    ContainerState,
)
from domain_checks.docker_unix import docker_unix_get_json

if TYPE_CHECKING:
    from domain_checks.container_models import (
        ContainerHealthOptions,
    )
    from domain_checks.types import JsonObject, JsonValue


def container_health_boundary_failure(error: str) -> ContainerHealthIssue:
    """Build a container-health issue for a Docker boundary failure.

    Returns:
        A normalized Docker-boundary issue.
    """
    return ContainerHealthIssue(
        name="docker",
        container_id="",
        running=None,
        status=None,
        restart_count=None,
        restart_increase=None,
        oom_killed=None,
        health_status=None,
        exit_code=None,
        error=error,
    )


def _compile_patterns(items: list[str] | None) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for item in items or []:
        expression = str(item or "").strip()
        if expression:
            patterns.append(re.compile(expression))
    return patterns


def _matches_any(name: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(name) for pattern in patterns)


def _container_name(entry: JsonObject, container_id: str) -> str:
    names = entry.get("Names")
    if isinstance(names, list) and names:
        name = str(names[0] or "").lstrip("/")
        if name:
            return name
    return container_id[:12]


def _selected_jobs(
    data: list[JsonValue],
    context: ContainerScanContext,
) -> list[ContainerJob]:
    jobs: list[ContainerJob] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        container_id = str(entry.get("Id") or "").strip()
        if not container_id:
            continue
        name = _container_name(entry, container_id)
        if _matches_any(name, context.exclude_patterns):
            continue
        if not context.monitor_all and not context.include_patterns:
            continue
        if not context.monitor_all and not _matches_any(name, context.include_patterns):
            continue
        status = str(entry.get("Status") or "").strip() or None
        jobs.append(ContainerJob(container_id, name, status))
    return jobs


def _health_status(state: JsonObject) -> str | None:
    health = state.get("Health")
    if not isinstance(health, dict):
        return None
    status = health.get("Status")
    return status.strip() if isinstance(status, str) and status.strip() else None


def _container_state(inspect_data: JsonObject) -> ContainerState:
    state_value = inspect_data.get("State")
    state = state_value if isinstance(state_value, dict) else {}
    running_value = state.get("Running")
    oom_value = state.get("OOMKilled")
    return ContainerState(
        running=running_value if isinstance(running_value, bool) else None,
        oom_killed=oom_value if isinstance(oom_value, bool) else None,
        exit_code=coerce_optional_int(state.get("ExitCode")),
        health_status=_health_status(state),
        restart_count=coerce_optional_int(inspect_data.get("RestartCount")),
    )


def _restart_increase(
    container_id: str,
    restart_count: int | None,
    previous_counts: dict[str, int],
) -> int | None:
    previous_count = previous_counts.get(container_id)
    if restart_count is None or previous_count is None:
        return None
    delta = restart_count - previous_count
    return delta if delta != 0 else None


def _state_is_bad(state: ContainerState, restart_increase: int | None) -> bool:
    unhealthy = bool(state.health_status and state.health_status != "healthy")
    restarted = restart_increase is not None and restart_increase > 0
    exited_with_error = state.exit_code not in {None, 0} and state.running is False
    return state.running is False or unhealthy or restarted or exited_with_error


def _inspection_failure(job: ContainerJob, error: str) -> ContainerHealthIssue:
    return ContainerHealthIssue(
        name=job.name,
        container_id=job.container_id[:12],
        running=None,
        status=job.status,
        restart_count=None,
        restart_increase=None,
        oom_killed=None,
        health_status=None,
        exit_code=None,
        error=error,
    )


async def _inspect_container(
    job: ContainerJob,
    context: ContainerScanContext,
    current_counts: dict[str, int],
) -> ContainerHealthIssue | None:
    async with context.semaphore:
        inspection = await asyncio.to_thread(
            docker_unix_get_json,
            socket_path=context.socket_path,
            path=f"/containers/{job.container_id}/json",
            timeout_seconds=context.timeout_seconds,
        )
    if not inspection.ok or not isinstance(inspection.data, dict):
        return _inspection_failure(
            job,
            f"docker_inspect_failed: {inspection.error or inspection.status}",
        )
    state = _container_state(inspection.data)
    if state.restart_count is not None:
        current_counts[job.container_id] = state.restart_count
    increase = _restart_increase(
        job.container_id,
        state.restart_count,
        context.previous_counts,
    )
    if not _state_is_bad(state, increase):
        return None
    return ContainerHealthIssue(
        name=job.name,
        container_id=job.container_id[:12],
        running=state.running,
        status=job.status,
        restart_count=state.restart_count,
        restart_increase=increase,
        oom_killed=state.oom_killed,
        health_status=state.health_status,
        exit_code=state.exit_code,
        error=None,
    )


async def check_container_health(
    *,
    docker_socket_path: str,
    **options: Unpack[ContainerHealthOptions],
) -> tuple[list[ContainerHealthIssue], dict[str, int]]:
    """Inspect configured containers through the Docker Unix socket.

    Returns:
        Container issues and current restart counts.
    """
    timeout_seconds = float(options.get("timeout_seconds", 3.0))
    listing = await asyncio.to_thread(
        docker_unix_get_json,
        socket_path=docker_socket_path,
        path="/containers/json?all=1",
        timeout_seconds=timeout_seconds,
    )
    if not listing.ok or not isinstance(listing.data, list):
        error = f"docker_list_failed: {listing.error or listing.status}"
        return [container_health_boundary_failure(error)], {}
    context = ContainerScanContext(
        socket_path=docker_socket_path,
        timeout_seconds=timeout_seconds,
        include_patterns=_compile_patterns(options["include_name_patterns"]),
        exclude_patterns=_compile_patterns(options["exclude_name_patterns"]),
        monitor_all=options["monitor_all"],
        previous_counts=options["previous_restart_counts"] or {},
        semaphore=asyncio.Semaphore(max(1, int(options.get("concurrency", 8)))),
    )
    current_counts: dict[str, int] = {}
    selected_jobs = _selected_jobs(listing.data, context)
    tasks = [asyncio.create_task(_inspect_container(job, context, current_counts)) for job in selected_jobs]
    issues: list[ContainerHealthIssue] = []
    for future in asyncio.as_completed(tasks):
        issue = await future
        if issue is not None:
            issues.append(issue)
    issues.sort(key=lambda issue: issue.name)
    return issues, current_counts
