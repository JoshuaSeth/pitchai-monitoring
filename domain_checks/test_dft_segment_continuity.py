# Copyright (c) 2026 PitchAI. All rights reserved.
"""Filesystem identity, complete-line and offset boundary regression tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .dft_access_segments import read_production_window
from .dft_segment_io import SegmentUnavailableError
from .dft_test_support import require, require_error

if TYPE_CHECKING:
    from .dft_segment_io import SegmentSnapshot


class TestContinuity(unittest.TestCase):
    """Read only synthetic disposable originals."""

    @staticmethod
    def test_prior_segment_identity_cannot_silently_change() -> None:
        """Replaced or shortened originals produce faults on later polls."""
        now = datetime.fromisoformat("2026-10-02T12:10:00+00:00")
        capture = "2026-10-02T12+00:00"
        row = json.dumps({"class": "dft-web-access-v1", "capture_hour": capture,
                          "event_unix": now.timestamp(), "status": 200, "agent": "client"}) + "\n"
        for mutation in ("truncate", "replace"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / f"dft-access-{capture}.jsonl"
                path.write_text(row, encoding="utf-8")
                snapshots: dict[str, SegmentSnapshot] = {}
                read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)
                if mutation == "replace":
                    replacement = root / "replacement"
                    replacement.write_text(row, encoding="utf-8")
                    replacement.replace(path)
                else:
                    path.write_text("", encoding="utf-8")
                with require_error(SegmentUnavailableError, "segment_replaced_or_truncated"):
                    read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)

    @staticmethod
    def test_partial_record_is_counted_once_when_completed() -> None:
        """Full recomputation counts offsets once, including after completion."""
        now = datetime.fromisoformat("2026-10-02T12:10:00+00:00")
        capture = "2026-10-02T12+00:00"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / f"dft-access-{capture}.jsonl"
            row = json.dumps({"class": "dft-web-access-v1", "capture_hour": capture,
                              "event_unix": now.timestamp(), "status": 404, "agent": "client"})
            path.write_text(row, encoding="utf-8")
            snapshots: dict[str, SegmentSnapshot] = {}
            before = read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\n")
            after = read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)
            again = read_production_window(root, now=now, window_seconds=300, snapshots=snapshots)
            require(condition=before.total == 0 and after.total == 1 and after.status_4xx == 1 and after == again,
                    message="partial completion or repeated polling counted the wrong offsets")

    @staticmethod
    def test_dst_fall_back_uses_explicit_offsets() -> None:
        """Two equal local hour labels denote separate original intervals."""
        now = datetime.fromisoformat("2026-10-25T02:01:00+01:00")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for capture, age in (("2026-10-25T02+02:00", 120), ("2026-10-25T02+01:00", 10)):
                row = {"class": "dft-web-access-v1", "capture_hour": capture,
                       "event_unix": now.timestamp() - age, "status": 200, "agent": "client"}
                (root / f"dft-access-{capture}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            result = read_production_window(root, now=now, window_seconds=300)
            expected_requests = 2
            require(condition=result.total == expected_requests,
                    message="offset-qualified repeated hour lost original events")
