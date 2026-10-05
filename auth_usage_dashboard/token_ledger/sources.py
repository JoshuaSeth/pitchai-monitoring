# Copyright (c) 2026 PitchAI. All rights reserved.
"""Discover rollout sources and resolve engine threads to lanes and projects.

Everything here is read-only: launch manifests and owner descriptors are
small JSON files, and cell control-plane databases are opened ``mode=ro``
with a generous busy timeout for a handful of indexed lookups.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

from .failures import ExpectedFailure

if TYPE_CHECKING:
    from collections.abc import Iterator

    from auth_usage_dashboard.timeseries_types import JsonObject, JsonValue, SqlValue

DEFAULT_CONFIG = Path("/etc/pitchai-token-ledger/config.json")
_PAAS_ROOT = Path("/", "tmp")  # The engine's own launch manifests, only ever read.
_MANIFEST_GLOB = "paas-*/.managed-app-server-systemd-launch-v1-*.json"
_OWNERS_ROOT = Path("/var/lib/pitchai-cli-new")
_OWNER_GLOB = "*-owners/*/owner.json"
_MAX_DESCRIPTOR_BYTES = 1024 * 1024
_SQLITE_TIMEOUT_SECONDS = 15.0
_PAIR = 2
_CONTROL_PLANE = "/code/pitchai-cli-new/.pitchai-state/control-plane.sqlite3"
_HOST_DEFAULTS: dict[str, JsonObject] = {
    "pitchai-dev": {
        "node": "master",
        "cells": [
            ["dev-main-cell-one", _CONTROL_PLANE],
            ["dev-monitoring-cell", "/code/pitchai-cli-new-monitoring/.pitchai-state/control-plane.sqlite3"],
        ],
        "extra_homes": [["/root/.codex", "voice"]],
        "delivery": "local",
    },
    "pitchai-jeff-dev": {"node": "jeff-dev", "cells": [["dev-jeff-cell-two", _CONTROL_PLANE]]},
    "pitchai-fsn1-01": {"node": "fsn1", "cells": [["pitchai-fsn1-01", _CONTROL_PLANE]]},
}
_OWNER_ROUTES = {"claude_code": "claude_code", "deepseek": "deepseek", "opencode_go": "opencode_go"}


@dataclass(frozen=True)
class Home:
    """One CODEX_HOME whose ``sessions`` tree holds rollouts."""

    path: str
    route: str


class NodeConfig(NamedTuple):
    """Per-host exporter configuration (defaults derive from the hostname)."""

    node: str
    cells: tuple[tuple[str, str], ...]
    extra_homes: tuple[tuple[str, str], ...] = ()
    delivery: str = "ssh"
    master: str = "root@135.181.182.48"
    ssh_key: str = "/root/.ssh/token_ledger_ed25519"
    known_hosts: str = "/var/lib/pitchai-token-ledger/known_hosts"
    backfill_days: int = 30
    max_bytes: int = 1536 * 1024 * 1024
    max_seconds: float = 150.0


@dataclass(frozen=True)
class Lane:
    """Resolved engine identity for one rollout thread."""

    cell: str
    agent: str
    project: str
    title: str | None


@dataclass
class LaneIndex:
    """Thread-id and worktree lookups loaded from every cell on this node."""

    by_thread: dict[str, Lane] = field(default_factory=dict)
    by_worktree: dict[str, Lane] = field(default_factory=dict)


def _read_json(path: Path) -> JsonObject | None:
    value: JsonValue = None
    with suppress(OSError, ValueError):
        if path.stat().st_size <= _MAX_DESCRIPTOR_BYTES:
            value = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    return value if isinstance(value, dict) else None


def _pairs(value: JsonValue) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return ()
    return tuple((str(item[0]), str(item[1])) for item in value if isinstance(item, list) and len(item) >= _PAIR)


def _text_option(merged: JsonObject, key: str, default: str) -> str:
    value = merged.get(key, default)
    return value if isinstance(value, str) and value else default


def _number_option(merged: JsonObject, key: str, default: float) -> float:
    value = merged.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return default
    return value


def load_config(path: Path = DEFAULT_CONFIG) -> NodeConfig:
    """Return the node configuration from the optional file over host defaults.

    Raises:
        RuntimeError: When neither the file nor the hostname names the node.
    """
    merged: JsonObject = dict(_HOST_DEFAULTS.get(os.uname().nodename.split(".")[0], {}))
    merged.update(_read_json(path) or {})
    node = merged.get("node")
    if not isinstance(node, str) or not node:
        message = "token ledger node name is not configured"
        raise RuntimeError(message)
    base = NodeConfig(node=node, cells=_pairs(merged.get("cells")), extra_homes=_pairs(merged.get("extra_homes")))
    return NodeConfig(
        node=node,
        cells=base.cells,
        extra_homes=base.extra_homes,
        delivery=_text_option(merged, "delivery", base.delivery),
        master=_text_option(merged, "master", base.master),
        ssh_key=_text_option(merged, "ssh_key", base.ssh_key),
        known_hosts=_text_option(merged, "known_hosts", base.known_hosts),
        backfill_days=int(_number_option(merged, "backfill_days", base.backfill_days)),
        max_bytes=int(_number_option(merged, "max_bytes", base.max_bytes)),
        max_seconds=float(_number_option(merged, "max_seconds", base.max_seconds)),
    )


def discover_homes(config: NodeConfig) -> list[Home]:
    """Return every distinct CODEX_HOME with a sessions tree on this host."""
    homes: dict[str, Home] = {}
    for manifest in _PAAS_ROOT.glob(_MANIFEST_GLOB):
        environment = (_read_json(manifest) or {}).get("process_env")
        home = environment.get("CODEX_HOME") if isinstance(environment, dict) else None
        if isinstance(home, str) and home:
            homes.setdefault(home, Home(home, "codex_account"))
    for descriptor in _OWNERS_ROOT.glob(_OWNER_GLOB):
        owner = _read_json(descriptor) or {}
        provider = owner.get("provider")
        route = _OWNER_ROUTES.get(provider, provider) if isinstance(provider, str) else None
        if descriptor.parent.parent.name == "astra-owners":
            route = "astra"
        home = str(descriptor.parent / "codex-home")
        homes.setdefault(home, Home(home, route or "owner"))
    for path, route in config.extra_homes:
        homes.setdefault(path, Home(path, route))
    return [home for home in homes.values() if Path(home.path, "sessions").is_dir()]


def list_rollouts(home: Home) -> list[tuple[str, os.stat_result]]:
    """Return every rollout file under the home with its stat result."""
    found: list[tuple[str, os.stat_result]] = []
    stack = [str(Path(home.path) / "sessions")]
    while stack:
        directory = stack.pop()
        entries: list[os.DirEntry[str]] = []
        with suppress(OSError):
            entries = list(os.scandir(directory))
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
            elif entry.name.startswith("rollout-") and entry.name.endswith(".jsonl"):
                with suppress(OSError):
                    found.append((entry.path, entry.stat()))
    return found


_LANE_QUERIES = (
    "select thread_id, agent_id from agents where thread_id is not null",
    "select runtime_session_id, agent_id from agent_runtime_sessions where runtime_session_id is not null",
    "select native_session_id, agent_id from runtime_migrations where native_session_id is not null",
    "select json_extract(previous_json, '$.binding[4]'), agent_id from runtime_migrations",
)


_AGENT_COLUMNS = ("project_id", "project_title", "worktree_path")
_AgentRow = tuple[str, "str | None", "str | None"]


def _agent_rows(connection: sqlite3.Connection) -> dict[str, _AgentRow]:
    """Return project, title and worktree per agent, reading only the columns this cell's schema has."""
    table_info = cast("Iterator[tuple[SqlValue, ...]]", connection.execute("pragma table_info(agents)"))
    columns = {str(row[1]) for row in table_info}
    selected = ", ".join(name if name in columns else "null" for name in _AGENT_COLUMNS)
    # Only allowlisted column names (or ``null``) are ever spliced into this query.
    query_parts = ("select agent_id,", selected, "from agents")
    query = " ".join(query_parts)
    agents: dict[str, _AgentRow] = {}
    for agent, project, title, worktree in cast("Iterator[tuple[SqlValue, ...]]", connection.execute(query)):
        agents[str(agent)] = (
            str(project or ""),
            title if isinstance(title, str) else None,
            worktree if isinstance(worktree, str) else None,
        )
    return agents


def _cell_rows(path: str) -> tuple[dict[str, _AgentRow], list[tuple[str, str]]]:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=_SQLITE_TIMEOUT_SECONDS)) as connection:
        agents = _agent_rows(connection)
        threads: list[tuple[str, str]] = []
        for lane_query in _LANE_QUERIES:
            with suppress(sqlite3.Error):
                pairs = cast("Iterator[tuple[SqlValue, SqlValue]]", connection.execute(lane_query))
                threads.extend((str(thread), str(agent)) for thread, agent in pairs if thread)
        return agents, threads


def load_lane_index(config: NodeConfig) -> tuple[LaneIndex, list[str]]:
    """Return lane lookups from every reachable cell plus per-cell error codes."""
    index = LaneIndex()
    errors: list[str] = []
    for cell, path in config.cells:
        if not Path(path).exists():
            continue
        agents: dict[str, _AgentRow] = {}
        threads: list[tuple[str, str]] = []
        with ExpectedFailure(sqlite3.Error) as failure:
            agents, threads = _cell_rows(path)
        if failure.name is not None:
            errors.append(f"{cell}:{failure.name}")
            continue
        for agent, (project, title, worktree) in agents.items():
            lane = Lane(cell, agent, project or "_unassigned", title)
            if worktree:
                index.by_worktree.setdefault(worktree.rstrip("/"), lane)
        for thread, agent in threads:
            project, title, _ = agents.get(agent, ("_unassigned", None, None))
            index.by_thread.setdefault(thread, Lane(cell, agent, project or "_unassigned", title))
    return index, errors
