# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock historical sampling and hourly reconstruction behavior."""

from __future__ import annotations

import json
import stat
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from auth_usage_dashboard.history import (
    UsageSampleStore,
    build_hourly_usage_history,
    capacity_burn_rate,
)
from domain_checks.testing import verify
from tests.auth_usage_history_support import NOW, account_fixture, sample_fixture

if TYPE_CHECKING:
    from pathlib import Path

OWNER_READ_WRITE_MODE = 0o600
EXPECTED_HISTORY_POINT_COUNT = 168
HOURS_PER_DAY = 24
EXPECTED_JULY_TENTH_TOKENS = 2_400
EXPECTED_CAPACITY_POINTS_PER_HOUR = 10


def test_sample_store_is_bounded_root_private_and_secret_free(tmp_path: Path) -> None:
    """Persist bounded samples in a private file without secret material."""
    path = tmp_path / "private" / "samples.json"
    store = UsageSampleStore(path, retention_days=8, sample_interval_seconds=300)
    account = account_fixture(daily=[{"date": NOW.date().isoformat(), "tokens": 400}])

    first = store.record([account], at=NOW)
    second = store.record([account], at=NOW + timedelta(minutes=1))

    verify(len(first) == 1)
    verify(second == first)
    encoded = path.read_text(encoding="utf-8")
    verify("must-not-escape" not in encoded)
    verify("access_token" not in encoded)
    verify("auth_json" not in encoded)
    verify(stat.S_IMODE(path.stat().st_mode) == OWNER_READ_WRITE_MODE)
    verify(json.loads(encoded)["schema_version"] == 1)


def test_sample_store_rejects_corrupt_history_instead_of_hiding_it(
    tmp_path: Path,
) -> None:
    """Reject corrupt persisted samples at their storage boundary."""
    path = tmp_path / "samples.json"
    _ = path.write_text(
        '{"schema_version":1,"samples":[{"at":"bad","accounts":{}}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid sample"):
        _ = UsageSampleStore(path).read()


def test_hourly_history_has_168_points_and_preserves_provider_daily_total() -> None:
    """Reconstruct 168 hourly points without changing provider daily totals."""
    account = account_fixture(
        daily=[
            {"date": "2026-07-10", "tokens": 2_400},
            {"date": "2026-07-11", "tokens": 1_300},
        ],
    )
    samples = [
        sample_fixture(NOW - timedelta(hours=2), 10, 800),
        sample_fixture(NOW - timedelta(hours=1), 20, 1_000),
        sample_fixture(NOW, 30, 1_300),
    ]

    history = build_hourly_usage_history([account], samples=samples, now=NOW)

    verify(history["granularity"] == "hour")
    verify(history["provider_granularity"] == "daily")
    verify(history["point_count"] == EXPECTED_HISTORY_POINT_COUNT)
    july_tenth = [point for point in history["combined"] if point["at"].startswith("2026-07-10")]
    verify(len(july_tenth) == HOURS_PER_DAY)
    july_tenth_tokens = (point["tokens"] for point in july_tenth)
    verify(sum(july_tenth_tokens) == EXPECTED_JULY_TENTH_TOKENS)
    verify(history["reconstruction"]["daily_totals_preserved"] is True)
    verify(history["reconstruction"]["native_samples_used"] is True)
    smoothed_fields = (
        "smoothed_tokens" in point for point in history["combined"]
    )
    verify(all(smoothed_fields))


def test_capacity_burn_prefers_native_trailing_samples() -> None:
    """Prefer native trailing samples when computing recent capacity burn."""
    samples = [
        sample_fixture(NOW - timedelta(hours=2), 10),
        sample_fixture(NOW - timedelta(hours=1), 20),
        sample_fixture(NOW, 30),
    ]

    burn = capacity_burn_rate([account_fixture()], samples=samples, now=NOW)

    verify(burn["source"] == "native_broker_samples")
    verify(burn["capacity_points_per_hour"] == EXPECTED_CAPACITY_POINTS_PER_HOUR)
    verify(burn["covered_accounts"] == 1)
