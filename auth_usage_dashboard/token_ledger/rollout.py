# Copyright (c) 2026 PitchAI. All rights reserved.
"""Incremental, byte-budgeted reader for codex-format rollout JSONL files.

Only three line kinds matter: ``session_meta`` (thread id, cwd),
``turn_context`` (model) and ``event_msg``/``token_count`` (usage). Every other
line is skipped by a cheap prefix check without JSON decoding. The cursor only
advances past complete lines, so a partially written line is read next time.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO

USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
_HEAD_BYTES = 200
_CHUNK_BYTES = 4 * 1024 * 1024
_MAX_INTERESTING_LINE = 8 * 1024 * 1024
_SESSION_META = b'"type":"session_meta"'
_TURN_CONTEXT = b'"type":"turn_context"'
_TOKEN_COUNT = b'"payload":{"type":"token_count"'
_TIMESTAMP = re.compile(rb'^\{"timestamp":"([^"]{10,40})"')
_SEEK_MIN_BYTES = 16 * 1024 * 1024
_SEEK_PRECISION = 1024 * 1024
_PRIMER_BYTES = 8 * 1024 * 1024
_HEAD_PRIMER_BYTES = 256 * 1024


@dataclass
class FileState:
    """Durable per-file cursor and the parse context needed to resume."""

    offset: int = 0
    thread_id: str | None = None
    cwd: str | None = None
    model: str | None = None
    last_total: tuple[int, ...] | None = None
    count_from: float = 0.0
    baseline_pending: bool = False


@dataclass(frozen=True)
class UsageEvent:
    """Tokens of one model request attributed to its event hour."""

    hour_epoch: int
    model: str | None
    usage: tuple[int, ...]


@dataclass
class ReadResult:
    """Events and bytes consumed by one bounded read of one file."""

    events: list[UsageEvent] = field(default_factory=list)
    consumed: int = 0


def _usage_tuple(raw: object) -> tuple[int, ...] | None:
    if not isinstance(raw, dict):
        return None
    values: list[int] = []
    for name in USAGE_FIELDS:
        value = raw.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            value = 0
        values.append(value)
    return tuple(values)


def _event_epoch(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def usage_delta(state: FileState, info: dict[str, object]) -> tuple[int, ...] | None:
    """Return the tokens of one ``token_count`` event, updating the baseline.

    Codex-family runtimes report a cumulative ``total_token_usage``: the usage
    is the delta, an unchanged total is a repeated event, and a lower total is
    a counter reset. Runtimes without a cumulative total (the Claude owner)
    report only ``last_token_usage`` per request.
    """
    total = _usage_tuple(info.get("total_token_usage"))
    if total is not None:
        previous = state.last_total
        state.last_total = total
        if state.baseline_pending:
            state.baseline_pending = False
            return None
        if previous is None or total[-1] < previous[-1]:
            return total if any(total) else None
        if total == previous:
            return None
        delta = tuple(max(0, now - before) for now, before in zip(total, previous))
        return delta if any(delta) else None
    last = _usage_tuple(info.get("last_token_usage"))
    return last if last is not None and any(last) else None


def _apply_line(state: FileState, line: bytes, result: ReadResult) -> None:
    head = line[:_HEAD_BYTES]
    if _TOKEN_COUNT not in head and _TURN_CONTEXT not in head and _SESSION_META not in head:
        return
    try:
        record = json.loads(line)
    except ValueError:
        return
    if not isinstance(record, dict):
        return
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return
    kind = record.get("type")
    if kind == "session_meta":
        thread_id, cwd = payload.get("id"), payload.get("cwd")
        state.thread_id = thread_id if isinstance(thread_id, str) else state.thread_id
        state.cwd = cwd if isinstance(cwd, str) else state.cwd
    elif kind == "turn_context":
        model = payload.get("model")
        state.model = model if isinstance(model, str) else state.model
    elif kind == "event_msg" and payload.get("type") == "token_count":
        info = payload.get("info")
        epoch = _event_epoch(record.get("timestamp"))
        delta = usage_delta(state, info) if isinstance(info, dict) else None
        if delta is not None and epoch is not None and epoch >= state.count_from:
            result.events.append(UsageEvent(int(epoch) // 3600 * 3600, state.model, delta))


def read_new_lines(handle: BinaryIO, state: FileState, *, budget: int) -> ReadResult:
    """Consume complete lines after ``state.offset`` up to ``budget`` bytes.

    Returns:
        Usage events found and the number of bytes the cursor advanced.
    """
    result = ReadResult()
    handle.seek(state.offset)
    pending = b""
    skipping = False
    while result.consumed < budget:
        chunk = handle.read(_CHUNK_BYTES)
        if not chunk:
            break
        buffer = pending + chunk
        start = 0
        while True:
            newline = buffer.find(b"\n", start)
            if newline < 0:
                break
            if not skipping:
                _apply_line(state, buffer[start:newline], result)
            skipping = False
            result.consumed += newline + 1 - start
            start = newline + 1
            if result.consumed >= budget:
                break
        pending = buffer[start:]
        if len(pending) > _MAX_INTERESTING_LINE and not skipping:
            # A huge line (tool output) is never a usage line: drop it as we read.
            skipping = _TOKEN_COUNT not in pending[:_HEAD_BYTES]
        if skipping:
            result.consumed += len(pending)
            pending = b""
        if result.consumed >= budget:
            break
    state.offset += result.consumed
    _drop_cache(handle, state.offset - result.consumed, result.consumed)
    return result


def _drop_cache(handle: BinaryIO, offset: int, length: int) -> None:
    """Tell the kernel these rollout pages are not worth caching (Linux only)."""
    advise = getattr(os, "posix_fadvise", None)
    flag = getattr(os, "POSIX_FADV_DONTNEED", None)
    if advise is not None and flag is not None and length > 0:
        try:
            advise(handle.fileno(), offset, length, flag)
        except OSError:
            return


def _skip_partial_line(handle: BinaryIO) -> None:
    while True:
        piece = handle.readline(_SEEK_PRECISION)
        if not piece or piece.endswith(b"\n"):
            return


def _line_epoch_at(handle: BinaryIO, position: int) -> tuple[int, float] | None:
    handle.seek(position)
    if position:
        _skip_partial_line(handle)
    start = handle.tell()
    match = _TIMESTAMP.match(handle.read(64))
    epoch = _event_epoch(match.group(1).decode("ascii", "replace")) if match else None
    return None if epoch is None else (start, epoch)


def prime_for_horizon(handle: BinaryIO, size: int, state: FileState) -> None:
    """Start a large, long-lived file near ``state.count_from`` instead of byte 0.

    A binary search on line timestamps finds the last line start before the
    horizon; the session header and a short primer before that point restore
    the thread id, model and cumulative baseline. Without a baseline the first
    cumulative total only primes the counter, so nothing is over-counted.
    """
    if size < _SEEK_MIN_BYTES:
        return
    first = _line_epoch_at(handle, 0)
    if first is None or first[1] >= state.count_from:
        return
    low, high = 0, size
    while high - low > _SEEK_PRECISION:
        middle = (low + high) // 2
        found = _line_epoch_at(handle, middle)
        if found is None or found[1] >= state.count_from:
            high = middle
        else:
            low = found[0]
    if low == 0:
        return
    head = FileState(count_from=float("inf"))
    read_new_lines(handle, head, budget=min(low, _HEAD_PRIMER_BYTES))
    state.thread_id = head.thread_id or state.thread_id
    state.cwd = head.cwd or state.cwd
    primer = FileState(count_from=float("inf"), model=head.model)
    if low > _PRIMER_BYTES:
        found = _line_epoch_at(handle, low - _PRIMER_BYTES)
        primer.offset = found[0] if found is not None and found[0] < low else low
    read_new_lines(handle, primer, budget=max(0, low - primer.offset))
    state.model = primer.model or state.model
    state.last_total = primer.last_total
    state.baseline_pending = primer.last_total is None
    state.offset = low
