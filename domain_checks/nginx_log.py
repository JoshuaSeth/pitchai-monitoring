# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded nginx log-file reads shared by metric parsers."""

from __future__ import annotations

import gzip
import os
from calendar import monthrange
from contextlib import suppress
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import tzinfo
    from pathlib import Path

type LogDateTimeParts = tuple[int, int, int, int, int, int]

_MIN_MONTH = 1
_MAX_MONTH = 12
_MIN_YEAR = 1
_MAX_YEAR = 9999
_MAX_HOUR = 23
_MAX_MINUTE_OR_SECOND = 59


def build_log_datetime(
    parts: LogDateTimeParts,
    *,
    local_tz: tzinfo,
) -> datetime | None:
    """Build a validated timezone-aware log timestamp.

    Returns:
        The parsed timestamp, or ``None`` for invalid calendar fields.
    """
    year, month, day, hour, minute, second = parts
    valid_month = _MIN_MONTH <= month <= _MAX_MONTH
    valid_date = valid_month and _MIN_YEAR <= year <= _MAX_YEAR
    if valid_date:
        valid_date = 1 <= day <= monthrange(year, month)[1]
    valid_time = (
        hour <= _MAX_HOUR
        and minute <= _MAX_MINUTE_OR_SECOND
        and second <= _MAX_MINUTE_OR_SECOND
    )
    if not valid_date or not valid_time:
        return None
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=local_tz,
    )


def _read_gzip_tail(path: Path, *, max_bytes: int) -> str:
    """Read a bounded decoded suffix from one gzip file.

    Returns:
        At most ``max_bytes`` decoded characters from the file suffix.
    """
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as stream:
        data = stream.read()
    return data[-max(1, max_bytes) :]


def _read_plain_tail(path: Path, *, max_bytes: int) -> str:
    """Read a bounded decoded suffix from one plain file.

    Returns:
        At most ``max_bytes`` decoded bytes from the file suffix.
    """
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        byte_count = max(1, min(max_bytes, size))
        stream.seek(size - byte_count, os.SEEK_SET)
        raw = stream.read(byte_count)
    return raw.decode("utf-8", errors="replace")


def read_log_tail(path: Path, *, max_bytes: int) -> str:
    """Read a bounded log tail.

    Returns:
        Decoded log text, or empty text after an I/O failure.
    """
    reader = _read_gzip_tail if path.suffix == ".gz" else _read_plain_tail
    text = ""
    with suppress(EOFError, OSError):
        text = reader(path, max_bytes=max_bytes)
    return text
