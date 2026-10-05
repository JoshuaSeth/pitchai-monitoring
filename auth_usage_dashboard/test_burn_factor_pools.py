# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the Claude and OpenCode burn-factor pools, their samples and blocking windows."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ._timeseries_test_fixtures import check, check_close, check_equal
from .burn_factor import build_burn_factors
from .burn_factor_capacity import AccountWindow, simulate
from .burn_factor_pools import claude_accounts, opencode_accounts, pool_inputs
from .burn_factor_windows import parse_pairs
from .opencode_accounts import account_row, pool_entries, sample_entry
from .pool_samples import append_sample, claude_sample, read_samples
from .timeseries_types import optional_object, require_object

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
EPOCH = NOW.timestamp()
PLANTED_KEY_TEXT = "sk-must-never-leak"


def test_blocked_account_serves_nothing_until_its_block_lifts() -> None:
    """Prove another exhausted window blocks an account and its points stay unusable."""
    blocked = AccountWindow(80.0, NOW + timedelta(days=3), timedelta(days=7), None, NOW + timedelta(days=10))
    capacity = simulate([blocked], start=NOW, rate=1.0, horizon_hours=24.0)
    check_close(capacity.effective_points, 0.0, "a blocked account offers nothing inside the window")
    check_close(capacity.losses.blocked_at_horizon_end, 80.0, "its points are reported as blocked")
    check_close(capacity.runway_hours or 0.0, 0.0, "demand cannot be served at all")


def test_opencode_rows_and_samples_never_carry_keys() -> None:
    """Prove the OpenCode exporter keeps labels and numbers only."""
    entries = pool_entries({
        "keys": [{"label": "info@pitchai.net", "api_key": PLANTED_KEY_TEXT}, PLANTED_KEY_TEXT + "2"],
    })
    check_equal([label for label, _ in entries], ["info@pitchai.net", "subscription-2"], "labels, never keys")
    usage: JsonObject = {
        "rolling": {"status": "ok", "percent": 10, "resetsAt": "2026-10-05T18:00:00.000Z"},
        "weekly": {"status": "ok", "percent": 25, "resetsAt": "2026-10-12T00:00:00.000Z"},
        "monthly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-10-22T17:00:00.000Z"},
    }
    row = account_row(
        "info@pitchai.net",
        usage,
        {"label": "info@pitchai.net", "last_status": 429, "cooldown_until": EPOCH},
    )
    sample = sample_entry(row)
    check(PLANTED_KEY_TEXT not in json.dumps([row, sample]), "no key in the row or the sample")
    check_equal(sample.get("weekly_used_percent"), 25.0, "the weekly percentage is sampled")
    check_equal(sample.get("monthly_reset_at"), "2026-10-22T17:00:00.000Z", "the monthly reset is sampled")


def test_opencode_monthly_limit_blocks_the_account_until_its_reset() -> None:
    """Prove an exhausted monthly window becomes the account's block."""
    usage: JsonObject = {
        "weekly": {"status": "ok", "percent": 0, "resetsAt": "2026-10-12T00:00:00.000Z"},
        "monthly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-10-22T17:00:00.000Z"},
    }
    snapshot: JsonObject = {"generated_at": EPOCH, "accounts": [account_row("a", usage, {})]}
    account = optional_object(opencode_accounts(snapshot, now=EPOCH)[0])
    check_equal(account.get("blocked_until"), "2026-10-22T17:00:00Z", "the monthly reset blocks the account")
    check_equal(optional_object(account.get("weekly")).get("remaining_percent"), 100.0, "weekly headroom is kept")


def test_claude_five_hour_limit_blocks_and_weekly_is_the_basis() -> None:
    """Prove Claude profiles map onto the weekly basis with the 5-hour window as a block."""
    snapshot: JsonObject = {
        "accounts": [
            {
                "email": "a@pitchai.net",
                "signed_in": True,
                "quota_observed_at": EPOCH,
                "windows": {
                    "seven_day": {"used_percent": 40.0, "resets_at": EPOCH + 86_400},
                    "five_hour": {"used_percent": 100.0, "resets_at": EPOCH + 3_600},
                },
            },
        ],
    }
    account = optional_object(claude_accounts(snapshot, now=EPOCH)[0])
    check_equal(optional_object(account.get("weekly")).get("remaining_percent"), 60.0, "weekly basis")
    check_equal(account.get("blocked_until"), "2026-10-05T13:00:00Z", "blocked until the 5-hour reset")
    sample = claude_sample(snapshot)
    accounts = optional_object(sample.get("accounts")) if sample is not None else {}
    check_equal(optional_object(accounts.get("a@pitchai.net")).get("weekly_used_percent"), 40.0, "sampled")


def test_samples_keep_a_four_minute_spacing_and_eight_days(tmp_path: Path) -> None:
    """Prove the sample store skips readings that are not newer and prunes old history."""
    path = tmp_path / "samples.json"
    old: JsonObject = {"at": "2026-09-20T00:00:00Z", "accounts": {}}
    first: JsonObject = {"at": "2026-10-05T12:00:00Z", "accounts": {}}
    close: JsonObject = {"at": "2026-10-05T12:02:00Z", "accounts": {}}
    later: JsonObject = {"at": "2026-10-05T12:05:00Z", "accounts": {}}
    check(append_sample(path, old, now=EPOCH - 15 * 86_400), "an old sample is written")
    check(append_sample(path, first, now=EPOCH), "a new sample is written")
    check(not append_sample(path, close, now=EPOCH), "a sample two minutes later is skipped")
    check(append_sample(path, later, now=EPOCH), "a sample five minutes later is written")
    check_equal([item.get("at") for item in read_samples(path)], [first["at"], later["at"]], "old history pruned")


def test_pool_inputs_feed_the_burn_factor_end_to_end(tmp_path: Path) -> None:
    """Prove a Claude snapshot plus samples yields a weekly-basis burn factor result."""
    snapshot: JsonObject = {
        "accounts": [
            {
                "email": "a@pitchai.net",
                "signed_in": True,
                "quota_observed_at": EPOCH,
                "windows": {"seven_day": {"used_percent": 50.0, "resets_at": EPOCH + 2 * 86_400}},
            },
        ],
    }
    (tmp_path / "claude-accounts.json").write_text(json.dumps(snapshot), encoding="utf-8")
    snap, samples = pool_inputs("anthropic", data_dir=tmp_path, now=EPOCH)
    payload = build_burn_factors(snap, samples, parse_pairs("30m:24h"), now=NOW)
    results = payload.get("results")
    result = require_object(results[0] if isinstance(results, list) else None, description="result")
    capacity = optional_object(result.get("capacity"))
    check_equal(capacity.get("left_now_points"), 50.0, "half the weekly window is left")
    check_equal(optional_object(payload.get("basis")).get("key"), "weekly", "weekly basis")
