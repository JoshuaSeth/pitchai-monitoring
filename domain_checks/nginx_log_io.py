# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded filesystem reads for Nginx monitoring logs."""

from __future__ import annotations

import gzip
import os
from pathlib import Path


def _binary_tail(path: Path, max_bytes: int) -> bytes:
    with path.open("rb") as stream:
        _ = stream.seek(0, os.SEEK_END)
        size = stream.tell()
        count = max(1, min(max_bytes, size))
        _ = stream.seek(size - count, os.SEEK_SET)
        return stream.read(count)


def _gzip_text(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as stream:
        return stream.read()


def tail_bytes(raw_path: str, *, max_bytes: int) -> str:
    """Read a bounded log tail, including gzip-compressed logs.

    Returns:
        Decoded log text, or an empty string when the log cannot be read.
    """
    path = Path(raw_path)
    if not path.exists():
        return ""
    if path.suffix == ".gz":
        try:
            data = _gzip_text(path)
        except (EOFError, OSError, UnicodeError):
            return ""
        return data[-max(1, int(max_bytes)) :]
    try:
        raw = _binary_tail(path, max(1, int(max_bytes)))
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")
