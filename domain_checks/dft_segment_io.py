# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded read-only access to original DFT hourly files."""

from __future__ import annotations

import os
import re
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from operator import itemgetter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_NAME = re.compile(r"dft-access-(\d{4}-\d{2}-\d{2}T\d{2}[+-]\d{2}:\d{2})\.jsonl")
_HOUR_SECONDS = 3600


class SegmentUnavailableError(ValueError):
    """The selected window cannot be trusted as complete coverage."""


@dataclass(frozen=True)
class SegmentCount:
    """Original-time aggregate counters; no request identifiers or content."""

    timestamp: float
    total: int
    server_errors: int
    gateway_errors: int
    client_errors: int


@dataclass(frozen=True)
class SegmentSnapshot:
    """Content-free continuity metadata retained between monitor cycles."""

    device: int
    inode: int
    size: int
    offset: int = 0
    covered_start: float = 0
    counts: tuple[SegmentCount, ...] = ()


@dataclass(frozen=True)
class SegmentChunk:
    """Bounded transient bytes at a stable segment position."""

    capture: str
    hour: float
    snapshot: SegmentSnapshot
    data: bytes
    reached_end: bool


@contextmanager
def _directory(root: Path) -> Generator[int]:
    """Pin the directory after opening every ancestor without following links.

    Yields:
        A read-only descriptor closed on completion or failure.
    """
    with ExitStack() as cleanup:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        cleanup.callback(os.close, descriptor)
        for part in root.absolute().parts[1:]:
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            cleanup.callback(os.close, descriptor)
        yield descriptor


def _select(directory: int, start: float, end: float) -> list[tuple[str, float, str]]:
    selected: list[tuple[str, float, str]] = []
    for name in os.listdir(directory):
        match = _NAME.fullmatch(name)
        if match is None:
            continue
        capture = match[1]
        hour = datetime.fromisoformat(capture[:13] + ":00:00" + capture[13:]).timestamp()
        if hour <= end and hour + _HOUR_SECONDS > start:
            selected.append((name, hour, capture))
    selected.sort(key=itemgetter(1))
    coverage = start
    for _, hour, _ in selected:
        if hour > coverage:
            message = "missing_window_segments"
            raise SegmentUnavailableError(message)
        coverage = max(coverage, hour + _HOUR_SECONDS)
    if coverage <= end:
        message = "missing_window_segments"
        raise SegmentUnavailableError(message)
    return selected


def _read_segment(
    directory: int, name: str, remaining: int, old: SegmentSnapshot | None,
) -> tuple[SegmentSnapshot, bytes]:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            message = "unsafe_segment_type_or_links"
            raise SegmentUnavailableError(message)
        if old is not None and (old.device != info.st_dev or old.inode != info.st_ino or old.size > info.st_size):
            message = "segment_replaced_or_truncated"
            raise SegmentUnavailableError(message)
        offset = old.offset if old else 0
        stream.seek(offset)
        expected = min(info.st_size - offset, remaining)
        data = stream.read(expected)
        if len(data) != expected:
            message = "segment_short_read"
            raise SegmentUnavailableError(message)
        snapshot = SegmentSnapshot(info.st_dev, info.st_ino, info.st_size, offset,
                                   old.covered_start if old else 0, old.counts if old else ())
    return snapshot, data


def load_window(
    root: Path, *, start: float, end: float, max_bytes: int, previous: dict[str, SegmentSnapshot],
) -> list[SegmentChunk]:
    """Read one bounded window and reject replacement or truncation.

    Returns:
        Transient incremental chunks, committed only after schema validation.
        The byte budget bounds work per poll rather than total hourly size.

    """
    result: list[SegmentChunk] = []
    remaining = max_bytes
    with _directory(root) as directory:
        for name, hour, capture in _select(directory, start, end):
            old = previous.get(name)
            if old is not None and start < old.covered_start:
                old = SegmentSnapshot(old.device, old.inode, old.size)
            snapshot, data = _read_segment(directory, name, remaining, old)
            remaining -= len(data)
            result.append(SegmentChunk(capture, hour, snapshot, data,
                                       snapshot.offset + len(data) == snapshot.size))
    return result
