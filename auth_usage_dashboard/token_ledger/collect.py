# Copyright (c) 2026 PitchAI. All rights reserved.
"""One bounded collection pass over every rollout on this node."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .labels import NON_LANE_PROJECT, normalize_model, provider_for
from .rollout import FileState, prime_for_horizon, read_new_lines
from .sources import Home, Lane, LaneIndex, discover_homes, list_rollouts, load_lane_index

if TYPE_CHECKING:
    from collections.abc import Callable

    from .node_store import NodeStore, RowKey, RowValues
    from .rollout import UsageEvent
    from .sources import NodeConfig

_THREAD_IN_NAME = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$")
_FORGET_AFTER_EXTRA_DAYS = 15
_DAY_SECONDS = 86_400


@dataclass
class CollectSummary:
    """What one pass did; persisted for status and freshness reporting."""

    homes: int = 0
    files_tracked: int = 0
    files_read: int = 0
    bytes_read: int = 0
    events: int = 0
    backlog_bytes: int = 0
    forgotten: int = 0
    lane_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidate:
    path: str
    inode: int
    size: int
    mtime: float
    home: Home
    state: FileState
    known: bool


def _thread_id(path: str, state: FileState) -> str | None:
    if state.thread_id:
        return state.thread_id
    match = _THREAD_IN_NAME.search(path)
    return match.group(1) if match else None


def _lane_for(index: LaneIndex, path: str, state: FileState) -> Lane | None:
    thread = _thread_id(path, state)
    lane = index.by_thread.get(thread) if thread else None
    if lane is None and state.cwd:
        lane = index.by_worktree.get(state.cwd.rstrip("/"))
    return lane


def rows_for(events: list[UsageEvent], lane: Lane | None, route: str) -> dict[RowKey, RowValues]:
    """Fold usage events of one file into hourly row increments."""
    rows: dict[RowKey, RowValues] = {}
    cell, agent, project, title = ("-", "-", NON_LANE_PROJECT, None) if lane is None else (lane.cell, lane.agent, lane.project, lane.title)
    for event in events:
        model = normalize_model(event.model)
        key = (event.hour_epoch, cell, project, agent, provider_for(model, route), model, route)
        _, totals = rows.setdefault(key, (title, [0, 0, 0, 0, 0, 0]))
        for position, value in enumerate(event.usage):
            totals[position] += value
        totals[5] += 1
    return rows


def _candidates(config: NodeConfig, store: NodeStore, homes: list[Home], now: float) -> tuple[list[_Candidate], list[str]]:
    horizon = now - config.backfill_days * _DAY_SECONDS
    known = store.cursors()
    found: list[_Candidate] = []
    present: list[str] = []
    for home in homes:
        for path, stat in list_rollouts(home):
            present.append(path)
            cursor = known.get(path)
            if cursor is None:
                if stat.st_mtime >= horizon:
                    found.append(_Candidate(path, stat.st_ino, stat.st_size, stat.st_mtime, home, FileState(count_from=horizon), known=False))
                continue
            _, _, state = cursor
            if stat.st_size < state.offset:
                # Truncated or replaced: restart, but never recount what was already counted.
                state = FileState(count_from=max(state.count_from, stat.st_mtime - 1))
            elif stat.st_size == state.offset:
                continue
            found.append(_Candidate(path, stat.st_ino, stat.st_size, stat.st_mtime, home, state, known=True))
    # Live files first (small appends), then backfill newest first.
    found.sort(key=lambda item: (not item.known, -item.mtime))
    return found, present


def collect(
    config: NodeConfig,
    store: NodeStore,
    *,
    now: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    home_finder: Callable[[NodeConfig], list[Home]] = discover_homes,
    lane_loader: Callable[[NodeConfig], tuple[LaneIndex, list[str]]] = load_lane_index,
) -> CollectSummary:
    """Read new rollout bytes within the byte and time budget and store rows.

    Returns:
        Summary of the pass, also persisted in the store's metadata.
    """
    started, wall = clock(), time.time() if now is None else now
    homes = home_finder(config)
    candidates, present = _candidates(config, store, homes, wall)
    summary = CollectSummary(homes=len(homes), files_tracked=len(present))
    index: LaneIndex | None = None
    remaining = config.max_bytes
    for position, item in enumerate(candidates):
        if remaining <= 0 or clock() - started >= config.max_seconds:
            summary.backlog_bytes += sum(entry.size - entry.state.offset for entry in candidates[position:])
            break
        if index is None:
            index, summary.lane_errors = lane_loader(config)
        try:
            with open(item.path, "rb") as handle:  # noqa: PTH123 - binary tail with explicit seek
                if not item.known:
                    prime_for_horizon(handle, item.size, item.state)
                result = read_new_lines(handle, item.state, budget=remaining)
        except OSError:
            continue
        remaining -= result.consumed
        summary.files_read += 1
        summary.bytes_read += result.consumed
        summary.events += len(result.events)
        rows = rows_for(result.events, _lane_for(index, item.path, item.state), item.home.route)
        store.commit_file(item.path, item.inode, item.home.route, item.state, rows)
        summary.backlog_bytes += max(0, item.size - item.state.offset)
    summary.forgotten = store.forget_stale(present, older_than=wall - (config.backfill_days + _FORGET_AFTER_EXTRA_DAYS) * _DAY_SECONDS)
    store.set_meta(
        {
            "last_collect_at": wall,
            "backlog_bytes": summary.backlog_bytes,
            "files_tracked": summary.files_tracked,
            "homes": summary.homes,
            "lane_errors": ",".join(summary.lane_errors),
            "collect_seconds": round(clock() - started, 3),
            "pid": os.getpid(),
        },
    )
    return summary
