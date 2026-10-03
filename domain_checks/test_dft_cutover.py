# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic shared/segment transitions preserve one authoritative DFT feed."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from .dft_access_cutover import DFT_PRODUCTION, DFT_STAGING, DftAccessCutover
from .dft_segment_io import SegmentUnavailableError
from .dft_test_support import require, require_error


def shared_line(host: str, now: datetime, status: int, agent: str = "client") -> str:
    """Build one synthetic deployed-format JSON record with recognizable content.

    Returns:
        A complete line for the isolated shared feed.
    """
    row = {"timestamp": now.isoformat(), "host": host, "status": status,
           "user_agent": agent, "ip": "192.0.2.1", "uri": "/synthetic-private"}
    return json.dumps(row) + "\n"


class TestDftCutover(unittest.TestCase):
    """All files are local synthetic records, with no bus or original-file access."""

    @staticmethod
    def test_feed_authority_and_unrelated_hosts() -> None:
        """The same DFT request in both sources counts exactly once per mode."""
        now = datetime.fromisoformat("2026-10-02T12:10:00+00:00")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production, staging = root / "production", root / "staging"
            production.mkdir()
            staging.mkdir()
            shared = root / "shared.log"
            shared.write_text(shared_line(DFT_PRODUCTION, now, 502) + shared_line("other.pitchai.net", now, 404)
                              + shared_line(DFT_STAGING, now, 504)
                              + shared_line(DFT_PRODUCTION, now, 504, "PitchAI Service Monitoring Bot"),
                              encoding="utf-8")
            capture = "2026-10-02T12+00:00"
            record = {"class": "dft-web-access-v1", "capture_hour": capture,
                      "event_unix": now.timestamp(), "status": 502, "agent": "client", "ip": "192.0.2.1"}
            name = f"dft-access-{capture}.jsonl"
            (production / name).write_text(json.dumps(record) + "\n", encoding="utf-8")
            (staging / name).write_text("invalid staging must never be read\n", encoding="utf-8")
            first = DftAccessCutover("shared", root / "absent")
            selected = DftAccessCutover("segments", production)
            before = first.read(access_log_path=str(shared), now=now, window_seconds=300)
            after = selected.read(access_log_path=str(shared), now=now, window_seconds=300)
            require(condition=before == after and after is not None, message="source cutover changed request counts")
            if after is not None:
                require(condition=(after.total, after.status_502_504, after.status_4xx) == (2, 1, 1),
                        message="DFT duplication, staging, probes or unrelated host counts are wrong")
                require(condition=not after.sample_lines, message="DFT raw content escaped into samples")
            (production / name).unlink()
            with require_error(SegmentUnavailableError, "missing_window_segments"):
                selected.read(access_log_path=str(shared), now=now, window_seconds=300)

    @staticmethod
    def test_unattributed_shared_data_cannot_enter_cutover() -> None:
        """A combined record without its host cannot safely exclude DFT."""
        now = datetime.fromisoformat("2026-10-02T12:10:00+00:00")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared.log"
            shared.write_text('192.0.2.1 - - [02/Oct/2026:12:10:00 +0000] "GET / HTTP/1.1" '
                              '200 0 "-" "client"\n', encoding="utf-8")
            selected = DftAccessCutover("segments", root / "absent")
            with require_error(ValueError, "shared_feed_host_unattributed"):
                selected.read(access_log_path=str(shared), now=now, window_seconds=300)
