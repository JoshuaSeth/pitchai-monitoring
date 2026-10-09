# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded catch-up for a large hour containing a tiny current window."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from .dft_access_segments import read_production_window
from .dft_journal import DftJournal
from .dft_segment_io import SegmentUnavailableError
from .dft_test_support import require, require_error

_POLL_BUDGET = 1_000_000
_COMPLETE_REQUESTS = 2
_INCLUDING_PARTIAL = 3


class TestIncrementalWindow(unittest.TestCase):
    """Synthetic originals exceed one poll's budget without a larger read."""

    @staticmethod
    def test_large_hour_catches_up_across_restart() -> None:
        """Resume the exact byte offset and retain distinct identical events."""
        now = datetime(2026, 10, 2, 12, 55, tzinfo=UTC)
        capture = "2026-10-02T12+00:00"
        old = {"class": "dft-web-access-v1", "capture_hour": capture,
               "event_unix": now.timestamp() - 3000, "status": 200, "agent": "private-old"}
        current = dict(old, event_unix=now.timestamp() - 1, status=502, agent="private-current")
        line = json.dumps(current) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / f"dft-access-{capture}.jsonl"
            old_line = json.dumps(old) + "\n"
            path.write_text(old_line * (_POLL_BUDGET // len(old_line) + 1) + line * 2 + line[:20], encoding="utf-8")
            require(condition=path.stat().st_size > _POLL_BUDGET, message="regression does not exceed old hour cap")
            journal = DftJournal(root / "consumer.sqlite")
            snapshots = journal.load_segments()
            with require_error(SegmentUnavailableError, "segment_catchup_incomplete"):
                read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)
            first = snapshots[path.name]
            require(condition=0 < first.offset <= _POLL_BUDGET and not first.counts,
                    message="cold scan exceeded byte budget or retained old request content")
            journal.save_segments(snapshots)
            journal.close()
            restored = DftJournal(root / "consumer.sqlite")
            snapshots = restored.load_segments()
            result = read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)
            require(condition=result.total == _COMPLETE_REQUESTS and result.status_502_504 == _COMPLETE_REQUESTS,
                    message="bounded resume lost or duplicated current requests")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line[20:])
            result = read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)
            require(condition=result.total == _INCLUDING_PARTIAL, message="partial final request was not counted once")
            require(condition=read_production_window(root, now=now, window_seconds=300, snapshots=snapshots) == result,
                    message="stable byte cursor counted identical requests again")
            restored.save_segments(snapshots)
            restored.close()
            require(condition=b"private-" not in (root / "consumer.sqlite").read_bytes(),
                    message="durable metadata copied raw request content")
