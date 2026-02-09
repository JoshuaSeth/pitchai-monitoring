from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from domain_checks.docker_unix import docker_unix_get_json


@dataclass(frozen=True)
class ContainerHealthIssue:
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


def _compile_patterns(items: Any) -> list[re.Pattern[str]]:
    if not isinstance(items, list):
        return []
    out: list[re.Pattern[str]] = []
    for x in items:
        s = str(x or "").strip()
        if not s:
            continue
        try:
            out.append(re.compile(s))
        except re.error:
            # Treat invalid regex as a literal substring match.
            out.append(re.compile(re.escape(s)))
    return out


def _matches_any(name: str, patterns: list[re.Pattern[str]]) -> bool:
    if not patterns:
        return False
    for p in patterns:
        try:
            if p.search(name):
                return True
        except Exception:
            continue
    return False


async def check_container_health(
    *,
    docker_socket_path: str,
    include_name_patterns: list[str] | None,
    exclude_name_patterns: list[str] | None,
    monitor_all: bool,
    previous_restart_counts: dict[str, int] | None,
    timeout_seconds: float = 3.0,
    concurrency: int = 8,
) -> tuple[list[ContainerHealthIssue], dict[str, int]]:
    """
    Returns: (issues, current_restart_counts_by_container_id)
    """
    include_p = _compile_patterns(include_name_patterns or [])
    exclude_p = _compile_patterns(exclude_name_patterns or [])
    prev = previous_restart_counts if isinstance(previous_restart_counts, dict) else {}

    listing = await asyncio.to_thread(
        docker_unix_get_json,
        socket_path=docker_socket_path,
        path="/containers/json?all=1",
        timeout_seconds=float(timeout_seconds),
    )
    if not listing.ok or not isinstance(listing.data, list):
        issue = ContainerHealthIssue(
            name="docker",
            container_id="",
            running=None,
            status=None,
            restart_count=None,
            restart_increase=None,
            oom_killed=None,
            health_status=None,
            exit_code=None,
            error=f"docker_list_failed: {listing.error or listing.status}",
        )
        return [issue], {}

    sem = asyncio.Semaphore(max(1, int(concurrency)))
    current_restart_counts: dict[str, int] = {}

    async def _inspect_one(container_id: str, name: str, status: str | None) -> ContainerHealthIssue | None:
        async with sem:
            insp = await asyncio.to_thread(
                docker_unix_get_json,
                socket_path=docker_socket_path,
                path=f"/containers/{container_id}/json",
                timeout_seconds=float(timeout_seconds),
            )
        if not insp.ok or not isinstance(insp.data, dict):
            return ContainerHealthIssue(
                name=name,
                container_id=container_id[:12],
                running=None,
                status=status,
                restart_count=None,
                restart_increase=None,
                oom_killed=None,
                health_status=None,
                exit_code=None,
                error=f"docker_inspect_failed: {insp.error or insp.status}",
            )

        state = insp.data.get("State") if isinstance(insp.data.get("State"), dict) else {}
        running = state.get("Running") if isinstance(state.get("Running"), bool) else None
        oom = state.get("OOMKilled") if isinstance(state.get("OOMKilled"), bool) else None
        exit_code = None
        try:
            if state.get("ExitCode") is not None:
                exit_code = int(state.get("ExitCode"))
        except Exception:
            exit_code = None

        health_status = None
        health = state.get("Health")
        if isinstance(health, dict):
            hs = health.get("Status")
            if isinstance(hs, str) and hs.strip():
                health_status = hs.strip()

        restart_count = None
        try:
            if insp.data.get("RestartCount") is not None:
                restart_count = int(insp.data.get("RestartCount"))
        except Exception:
            restart_count = None

        if restart_count is not None:
            current_restart_counts[container_id] = restart_count

        prev_count = prev.get(container_id)
        restart_increase = None
        if restart_count is not None and prev_count is not None:
            try:
                delta = int(restart_count) - int(prev_count)
                if delta != 0:
                    restart_increase = delta
            except Exception:
                restart_increase = None

        # Decide if this container is in a bad state.
        bad = False
        if running is False:
            bad = True
        if isinstance(health_status, str) and health_status and health_status != "healthy":
            bad = True
        if oom is True:
            bad = True
        if restart_increase is not None and restart_increase > 0:
            bad = True
        if exit_code is not None and exit_code != 0 and running is False:
            bad = True

        if not bad:
            return None

        return ContainerHealthIssue(
            name=name,
            container_id=container_id[:12],
            running=running,
            status=status,
            restart_count=restart_count,
            restart_increase=restart_increase,
            oom_killed=oom,
            health_status=health_status,
            exit_code=exit_code,
            error=None,
        )

    tasks: list[asyncio.Task[ContainerHealthIssue | None]] = []
    for entry in listing.data:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("Id") or "").strip()
        if not cid:
            continue
        names = entry.get("Names")
        name = ""
        if isinstance(names, list) and names:
            name = str(names[0] or "").lstrip("/")
        if not name:
            name = cid[:12]
        status = str(entry.get("Status") or "").strip() or None

        if _matches_any(name, exclude_p):
            continue
        if not monitor_all and include_p and not _matches_any(name, include_p):
            continue
        if not monitor_all and not include_p:
            continue

        tasks.append(asyncio.create_task(_inspect_one(cid, name, status)))

    issues: list[ContainerHealthIssue] = []
    for fut in asyncio.as_completed(tasks):
        r = await fut
        if r is not None:
            issues.append(r)

    issues.sort(key=lambda x: x.name)
    return issues, current_restart_counts

