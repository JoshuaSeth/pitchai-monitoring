from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from auth_usage_dashboard.history import (
    UsageSampleStore,
    build_hourly_usage_history,
    capacity_burn_rate,
)
from auth_usage_dashboard.runout import _first_runout, build_runout_forecast


UTC = timezone.utc
NOW = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)


def _account(
    label: str = "operator@example.com",
    *,
    remaining: float = 70,
    used: float = 30,
    weekly_remaining: float = 80,
    reset_at: datetime | None = None,
    daily: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "label": label,
        "email": label,
        "enabled": True,
        "auth_valid": True,
        "status": "available",
        "availability": "available",
        "selectable_now": True,
        "stale": False,
        "five_hour": {
            "reported": True,
            "used_percent": used,
            "remaining_percent": remaining,
            "reset_at": (reset_at or NOW + timedelta(hours=3)).isoformat(),
            "window_seconds": 18_000,
        },
        "weekly": {
            "reported": True,
            "used_percent": 100 - weekly_remaining,
            "remaining_percent": weekly_remaining,
            "reset_at": (NOW + timedelta(days=5)).isoformat(),
            "window_seconds": 604_800,
        },
        "token_usage": {
            "available": True,
            "daily": daily or [],
            "updated_at": NOW.isoformat(),
            "stale": False,
        },
        "reset_credits": {"available_count": 0, "details": [], "stale": False},
    }


def _sample(at: datetime, used: float, tokens: int = 0) -> dict[str, object]:
    return {
        "at": at.isoformat().replace("+00:00", "Z"),
        "accounts": {
            "operator@example.com": {
                "enabled": True,
                "auth_valid": True,
                "status": "available",
                "five_used_percent": used,
                "five_reset_at": (NOW + timedelta(hours=3)).isoformat(),
                "weekly_used_percent": 20,
                "weekly_reset_at": (NOW + timedelta(days=5)).isoformat(),
                "token_date": at.date().isoformat(),
                "tokens_today": tokens,
            }
        },
    }


def test_sample_store_is_bounded_root_private_and_secret_free(tmp_path: Path) -> None:
    path = tmp_path / "private" / "samples.json"
    store = UsageSampleStore(path, retention_days=8, sample_interval_seconds=300)
    account = _account(daily=[{"date": NOW.date().isoformat(), "tokens": 400}])
    account["access_token"] = "must-not-escape"
    account["auth_json"] = {"refresh_token": "must-not-escape"}

    first = store.record([account], at=NOW)
    second = store.record([account], at=NOW + timedelta(minutes=1))

    assert len(first) == 1
    assert second == first
    encoded = path.read_text(encoding="utf-8")
    assert "must-not-escape" not in encoded
    assert "access_token" not in encoded
    assert "auth_json" not in encoded
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(encoded)["schema_version"] == 1


def test_sample_store_rejects_corrupt_history_instead_of_hiding_it(tmp_path: Path) -> None:
    path = tmp_path / "samples.json"
    path.write_text('{"schema_version":1,"samples":[{"at":"bad","accounts":{}}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid sample"):
        UsageSampleStore(path).read()


def test_hourly_history_has_168_points_and_preserves_provider_daily_total() -> None:
    account = _account(
        daily=[
            {"date": "2026-07-10", "tokens": 2_400},
            {"date": "2026-07-11", "tokens": 1_300},
        ]
    )
    samples = [
        _sample(NOW - timedelta(hours=2), 10, 800),
        _sample(NOW - timedelta(hours=1), 20, 1_000),
        _sample(NOW, 30, 1_300),
    ]

    history = build_hourly_usage_history([account], samples=samples, now=NOW)

    assert history["granularity"] == "hour"
    assert history["provider_granularity"] == "daily"
    assert history["point_count"] == 168
    july_tenth = [point for point in history["combined"] if point["at"].startswith("2026-07-10")]
    assert len(july_tenth) == 24
    assert sum(point["tokens"] for point in july_tenth) == 2_400
    assert history["reconstruction"]["daily_totals_preserved"] is True
    assert history["reconstruction"]["native_samples_used"] is True
    assert all("smoothed_tokens" in point for point in history["combined"])


def test_capacity_burn_prefers_native_trailing_samples() -> None:
    samples = [
        _sample(NOW - timedelta(hours=2), 10),
        _sample(NOW - timedelta(hours=1), 20),
        _sample(NOW, 30),
    ]

    burn = capacity_burn_rate([_account()], samples=samples, now=NOW)

    assert burn["source"] == "native_broker_samples"
    assert burn["capacity_points_per_hour"] == 10
    assert burn["covered_accounts"] == 1


def test_first_runout_accounts_for_reset_arrival_without_redeeming_bank() -> None:
    reset_at = NOW + timedelta(minutes=30)
    no_outage = _first_runout(
        {"operator@example.com": 10.0},
        [{"at": reset_at, "account_label": "operator@example.com", "capacity_points": 100.0}],
        now=NOW,
        horizon_end=NOW + timedelta(hours=1),
        burn_rate_per_hour=20.0,
    )
    outage = _first_runout(
        {"operator@example.com": 10.0},
        [{"at": reset_at + timedelta(minutes=1), "account_label": "operator@example.com", "capacity_points": 100.0}],
        now=NOW,
        horizon_end=NOW + timedelta(hours=1),
        burn_rate_per_hour=20.0,
    )

    assert no_outage is None
    assert outage == NOW + timedelta(minutes=30)


def test_runout_forecast_excludes_banked_resets_from_capacity() -> None:
    samples = [
        _sample(NOW - timedelta(hours=2), 10),
        _sample(NOW - timedelta(hours=1), 50),
        _sample(NOW, 90),
    ]
    account = _account(remaining=10, used=90, reset_at=NOW + timedelta(hours=4))
    empty_bank = {"total_available": 0}
    large_bank = {"total_available": 99}

    without_bank = build_runout_forecast([account], samples=samples, reset_bank=empty_bank, now=NOW)
    with_bank = build_runout_forecast([account], samples=samples, reset_bank=large_bank, now=NOW)

    assert with_bank["horizons"] == without_bank["horizons"]
    assert with_bank["banked_reset_policy"]["included_as_automatic_capacity"] is False
    assert with_bank["banked_reset_policy"]["available_count"] == 99
    assert with_bank["horizons"][0]["probability_percent"] > 0


def test_runout_forecast_does_not_infer_zero_from_unreported_five_hour_window() -> None:
    account = _account()
    account["five_hour"] = {
        "reported": False,
        "used_percent": None,
        "remaining_percent": None,
        "reset_at": None,
        "window_seconds": None,
    }

    forecast = build_runout_forecast(
        [account],
        samples=[],
        reset_bank={"total_available": 3},
        now=NOW,
    )

    assert forecast["data_available"] is False
    assert forecast["usable_accounts_now"] == 1
    assert forecast["highest_probability_percent"] is None
    assert all(item["probability_percent"] is None for item in forecast["horizons"])
    assert all(item["risk"] == "unknown" for item in forecast["horizons"])
    assert forecast["banked_reset_policy"]["included_as_automatic_capacity"] is False
