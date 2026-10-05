# Copyright (c) 2026 PitchAI. All rights reserved.
"""One bounded collection pass over every rollout on this node."""

from __future__ import annotations

import os
import re
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from .labels import NON_LANE_PROJECT, normalize_model, provider_for
from .node_store import FileCursor
from .rollout import FileState, prime_for_horizon, read_new_lines
from .sources import discover_homes, list_rollouts, load_lane_index

if TYPE_CHECKING:
    from collections.abc import Callable

    from auth_usage_dashboard.timeseries_types import JsonObject

    from .node_store import NodeStore, RowKey, RowValues
    from .rollout import ReadResult, UsageEvent
    from .sources import Home, Lane, LaneIndex, NodeConfig

_THREAD_IN_NAME = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$")
_FORGET_AFTER_EXTRA_DAYS = 15
_DAY_SECONDS = 86_400


@dataclass(frozen=True)
class CollectHooks:
    """Injectable clock and discovery seams (tests replace them)."""

    clock: Callable[[], float] = time.monotonic
    home_finder: Callable[[NodeConfig], list[Home]] = discover_homes
    lane_loader: Callable[[NodeConfig], tuple[LaneIndex, list[str]]] = load_lane_index


class CollectSummary(NamedTuple):
    """What one pass did; persisted for status and freshness reporting."""

    homes: int
    files_tracked: int
    files_read: int
    bytes_read: int
    events: int
    backlog_bytes: int
    forgotten: int
    lane_errors: list[str]

    def as_json(self) -> JsonObject:
        """Return the summary in the exporter's JSON ``collect`` report shape."""
        return {
            "homes": self.homes,
            "files_tracked": self.files_tracked,
            "files_read": self.files_read,
            "bytes_read": self.bytes_read,
            "events": self.events,
            "backlog_bytes": self.backlog_bytes,
            "forgotten": self.forgotten,
            "lane_errors": [*self.lane_errors],
        }


@dataclass
class _Progress:
    """Mutable counters of the read loop, folded into the summary afterwards."""

    files_read: int = 0
    bytes_read: int = 0
    events: int = 0
    backlog_bytes: int = 0
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
    """Fold usage events of one file into hourly row increments.

    Returns:
        Row increments keyed by hour, lane, provider, model and route.
    """
    rows: dict[RowKey, RowValues] = {}
    cell, agent, project, title = (
        ("-", "-", NON_LANE_PROJECT, None) if lane is None else (lane.cell, lane.agent, lane.project, lane.title)
    )
    for event in events:
        model = normalize_model(event.model)
        key = (event.hour_epoch, cell, project, agent, provider_for(model, route), model, route)
        _, totals = rows.setdefault(key, (title, [0, 0, 0, 0, 0, 0]))
        for position, value in enumerate(event.usage):
            totals[position] += value
        totals[5] += 1
    return rows


def _candidates(
    config: NodeConfig,
    store: NodeStore,
    homes: list[Home],
    now: float,
) -> tuple[list[_Candidate], list[str]]:
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
                    found.append(
                        _Candidate(
                            path,
                            stat.st_ino,
                            stat.st_size,
                            stat.st_mtime,
                            home,
                            FileState(count_from=horizon),
                            known=False,
                        ),
                    )
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


def _read_candidates(
    config: NodeConfig,
    store: NodeStore,
    candidates: list[_Candidate],
    seams: CollectHooks,
    started: float,
) -> _Progress:
    """Return the progress of tailing candidates in order, committing each file, until a budget runs out."""
    progress = _Progress()
    index: LaneIndex | None = None
    remaining = config.max_bytes
    for position, item in enumerate(candidates):
        if remaining <= 0 or seams.clock() - started >= config.max_seconds:
            progress.backlog_bytes += sum(entry.size - entry.state.offset for entry in candidates[position:])
            break
        if index is None:
            index, progress.lane_errors = seams.lane_loader(config)
        result: ReadResult | None = None
        with suppress(OSError), Path(item.path).open("rb") as handle:
            if not item.known:
                prime_for_horizon(handle, item.size, item.state)
            result = read_new_lines(handle, item.state, budget=remaining)
        if result is None:
            continue
        remaining -= result.consumed
        progress.files_read += 1
        progress.bytes_read += result.consumed
        progress.events += len(result.events)
        rows = rows_for(result.events, _lane_for(index, item.path, item.state), item.home.route)
        store.commit_file(FileCursor(item.path, item.inode, item.home.route, item.state), rows)
        progress.backlog_bytes += max(0, item.size - item.state.offset)
    return progress


def collect(
    config: NodeConfig,
    store: NodeStore,
    *,
    now: float | None = None,
    hooks: CollectHooks | None = None,
) -> CollectSummary:
    """Read new rollout bytes within the byte and time budget and store rows.

    Returns:
        Summary of the pass, also persisted in the store's metadata.
    """
    seams = hooks or CollectHooks()
    clock = seams.clock
    started, wall = clock(), time.time() if now is None else now
    homes = seams.home_finder(config)
    candidates, present = _candidates(config, store, homes, wall)
    progress = _read_candidates(config, store, candidates, seams, started)
    summary = CollectSummary(
        homes=len(homes),
        files_tracked=len(present),
        files_read=progress.files_read,
        bytes_read=progress.bytes_read,
        events=progress.events,
        backlog_bytes=progress.backlog_bytes,
        forgotten=store.forget_stale(
            present,
            older_than=wall - (config.backfill_days + _FORGET_AFTER_EXTRA_DAYS) * _DAY_SECONDS,
        ),
        lane_errors=progress.lane_errors,
    )
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
