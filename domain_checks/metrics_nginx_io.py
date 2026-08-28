# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read bounded plain-text and gzip Nginx log tails."""

from __future__ import annotations

import gzip
import os
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def read_log_tail(path: Path, *, max_bytes: int) -> str:
    """Read a bounded log tail, returning empty text when the file is unavailable.

    Returns:
        The decoded tail, or an empty string when the path cannot be read.
    """
    with suppress(OSError, EOFError):
        if not path.exists():
            return ""
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as compressed_file:
                data = compressed_file.read()
            return data[-max(1, max_bytes) :]

        with path.open("rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            read_size = max(1, min(max_bytes, size))
            log_file.seek(size - read_size, os.SEEK_SET)
            raw = log_file.read(read_size)
        return raw.decode("utf-8", errors="replace")
    return ""
