# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated segment coverage and content-minimization contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from .dft_access_segments import read_production_window
from .dft_segment_io import SegmentUnavailableError
from .dft_test_support import require, require_error


class TestSegments(unittest.TestCase):
    """Use synthetic local files only; no bus, nginx or customer records."""

    @staticmethod
    def test_boundary_and_partial_write() -> None:
        """Read both hours, wait for a partial line and retain only counts."""
        now = datetime(2026, 10, 2, 12, 1, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for hour, age, status in ((11, 120, 502), (12, 10, 200)):
                capture = f"2026-10-02T{hour:02d}+00:00"
                row = {"class": "dft-web-access-v1", "capture_hour": capture,
                       "event_unix": now.timestamp() - age, "status": status,
                       "agent": "private-agent", "ip": "192.0.2.1"}
                (root / f"dft-access-{capture}.jsonl").write_text(
                    json.dumps(row) + '\n{"incomplete":', encoding="utf-8",
                )
            result = read_production_window(root, now=now, window_seconds=300)
            require(condition=(result.total, result.status_502_504, result.sample_lines) == (2, 1, []),
                    message="window counters or content minimization changed")
            require(condition=read_production_window(root, now=now, window_seconds=300) == result,
                    message="repeated polling changed the window")
            with require_error(SegmentUnavailableError, "segment_catchup_incomplete"):
                read_production_window(root, now=now, window_seconds=300, max_bytes=5)
            (root / "dft-access-2026-10-02T11+00:00.jsonl").unlink()
            with require_error(SegmentUnavailableError, "missing_window_segments"):
                read_production_window(root, now=now, window_seconds=300)

    @staticmethod
    def test_identical_requests_are_distinct_and_bot_is_excluded() -> None:
        """Content equality is not a request identity."""
        now = datetime(2026, 10, 2, 12, 10, tzinfo=UTC)
        capture = "2026-10-02T12+00:00"
        row = {"class": "dft-web-access-v1", "capture_hour": capture,
               "event_unix": now.timestamp() - 1, "status": 503, "agent": "client"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = json.dumps(row) + "\n"
            row["agent"] = "PitchAI Service Monitoring Bot"
            path = root / f"dft-access-{capture}.jsonl"
            path.write_text(client * 2 + json.dumps(row) + "\n", encoding="utf-8")
            result = read_production_window(root, now=now, window_seconds=300)
            require(condition=(result.total, result.status_5xx) == (2, 2),
                    message="duplicate content was collapsed or bot counted")
            path.unlink()
            path.symlink_to(root / "missing")
            with require_error(OSError, "Too many levels of symbolic links"):
                read_production_window(root, now=now, window_seconds=300)
