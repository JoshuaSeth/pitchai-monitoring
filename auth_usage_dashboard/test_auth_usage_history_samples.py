# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the legacy JSON sample store, hourly history, and burn-rate estimate."""

from __future__ import annotations

import json
import stat
from datetime import timedelta
from typing import TYPE_CHECKING, cast

from ._broker_account_test_fixtures import LEAK_MARKER, integer, json_object, member, objects, text
from ._mobile_test_runtime import RAISES
from ._timeseries_test_fixtures import check, check_equal
from ._usage_history_test_fixtures import NOW, OPERATOR, dashboard_account, trailing_samples, usage_sample
from .history import UsageSampleStore, build_hourly_usage_history, capacity_burn_rate
from .timeseries_types import require_object

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject, JsonValue

PRIVATE_FILE_MODE = 0o600
HOURS_PER_DAY = 24
CORRUPT_LEDGER = '{"schema_version":1,"samples":[{"at":"bad","accounts":{}}]}'


def test_sample_store_is_bounded_root_private_and_secret_free(tmp_path: Path) -> None:
    """Prove the sample store deduplicates, stays owner-private, and drops secrets."""
    path = tmp_path / "private" / "samples.json"
    store = UsageSampleStore(path, retention_days=8, sample_interval_seconds=300)
    account = dashboard_account(daily=[{"date": NOW.date().isoformat(), "tokens": 400}])
    account["access_token"] = LEAK_MARKER
    account["auth_json"] = {"refresh_token": LEAK_MARKER}

    first = store.record([account], at=NOW)
    second = store.record([account], at=NOW + timedelta(minutes=1))

    check_equal(len(first), 1, "one bounded sample")
    check_equal(second, first, "a sample inside the interval is not duplicated")
    encoded = path.read_text(encoding="utf-8")
    check(LEAK_MARKER not in encoded, "secret values are not persisted")
    check("access_token" not in encoded, "access token key is not persisted")
    check("auth_json" not in encoded, "auth JSON key is not persisted")
    check_equal(stat.S_IMODE(path.stat().st_mode), PRIVATE_FILE_MODE, "sample file mode")
    ledger = require_object(cast("JsonValue", json.loads(encoded)), description="sample ledger")
    check_equal(ledger["schema_version"], 1, "sample ledger schema version")


def test_sample_store_rejects_corrupt_history_instead_of_hiding_it(tmp_path: Path) -> None:
    """Prove a corrupt sample ledger raises instead of reading as empty history."""
    path = tmp_path / "samples.json"
    path.write_text(CORRUPT_LEDGER, encoding="utf-8")

    with RAISES(ValueError) as captured:
        UsageSampleStore(path).read()

    check("invalid sample" in str(captured.value), "corrupt history error message")


def test_hourly_history_has_168_points_and_preserves_provider_daily_total() -> None:
    """Prove hourly reconstruction keeps 168 points and each provider daily total."""
    account = dashboard_account(
        daily=[
            {"date": "2026-07-10", "tokens": 2_400},
            {"date": "2026-07-11", "tokens": 1_300},
        ],
    )
    samples = [
        usage_sample(NOW - timedelta(hours=2), 10, 800),
        usage_sample(NOW - timedelta(hours=1), 20, 1_000),
        usage_sample(NOW, 30, 1_300),
    ]

    history = json_object(build_hourly_usage_history([account], samples=samples, now=NOW))

    check_equal(history["granularity"], "hour", "history granularity")
    check_equal(history["provider_granularity"], "daily", "provider granularity")
    check_equal(history["point_count"], 168, "hourly points")
    points = objects(history["combined"], "combined history")
    july_tenth = [point for point in points if text(point["at"], "point time").startswith("2026-07-10")]
    july_tenth_tokens = sum(integer(point["tokens"], "point tokens") for point in july_tenth)
    check_equal(len(july_tenth), HOURS_PER_DAY, "hours on July 10")
    check_equal(july_tenth_tokens, 2_400, "July 10 provider total")
    reconstruction = member(history, "reconstruction")
    check(reconstruction["daily_totals_preserved"] is True, "daily totals are preserved")
    check(reconstruction["native_samples_used"] is True, "native samples are used")
    smoothed = all("smoothed_tokens" in point for point in points)
    check(smoothed, "every point carries a smoothed value")


def test_capacity_burn_prefers_native_trailing_samples() -> None:
    """Prove the burn rate comes from native broker samples when they exist."""
    samples = trailing_samples(10, 20, 30)

    burn = json_object(capacity_burn_rate([dashboard_account()], samples=samples, now=NOW))

    check_equal(burn["source"], "native_broker_samples", "burn source")
    check_equal(burn["capacity_points_per_hour"], 10, "burn points per hour")
    check_equal(burn["covered_accounts"], 1, "accounts covered by the burn")


def test_weekly_burn_recovers_legacy_samples_that_were_mislabeled_five_hour() -> None:
    """Prove weekly burn reads legacy samples whose five-hour fields held weekly data."""
    legacy_reset = (NOW + timedelta(days=5)).isoformat()
    samples: list[JsonObject] = []
    for hours_ago, used in ((2, 10), (1, 20), (0, 30)):
        mislabeled: JsonObject = {"five_used_percent": used, "five_reset_at": legacy_reset}
        at = (NOW - timedelta(hours=hours_ago)).isoformat()
        samples.append({"at": at, "accounts": {OPERATOR: mislabeled}})

    burn = json_object(capacity_burn_rate([dashboard_account()], samples=samples, now=NOW, window_key="weekly"))

    check_equal(burn["source"], "native_broker_samples", "weekly burn source")
    check_equal(burn["window_key"], "weekly", "weekly burn window")
    check_equal(burn["capacity_points_per_hour"], 10, "weekly burn points per hour")
