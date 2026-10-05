# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the DeepSeek API balance exporter and its money burn factor."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ._timeseries_test_fixtures import check, check_close, check_equal
from .burn_factor_windows import parse_pairs
from .deepseek_balance import balance_row, owner_keys
from .deepseek_burn import build_deepseek_burn, hour_cost, window_usd
from .timeseries_types import optional_object, require_object
from .token_ledger.fleet_store import connect_fleet

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject

NOW = datetime(2026, 10, 5, 12, 30, tzinfo=UTC).timestamp()
OFF_PEAK_HOUR = datetime(2026, 10, 5, 11, 0, tzinfo=UTC).timestamp()
PEAK_HOUR = datetime(2026, 10, 5, 2, 0, tzinfo=UTC).timestamp()
SATURDAY_PEAK_CLOCK = datetime(2026, 10, 3, 2, 0, tzinfo=UTC).timestamp()
PLANTED_KEY_TEXT = "sk-deepseek-must-never-leak"
MILLION = 1_000_000


def test_hour_cost_applies_the_rates_and_the_weekday_peak() -> None:
    """Prove cached, uncached and output tokens are priced apart and weekday peaks double."""
    base = hour_cost(OFF_PEAK_HOUR, 2 * MILLION, MILLION, MILLION)
    check_close(base, 0.003 + 0.15 + 0.60, "one million of each kind at the snapshot rates")
    check_close(hour_cost(PEAK_HOUR, 2 * MILLION, MILLION, MILLION), 2 * base, "weekday 01-04 UTC is doubled")
    check_close(hour_cost(SATURDAY_PEAK_CLOCK, 2 * MILLION, MILLION, MILLION), base, "weekends are never peak")


def test_window_spend_prorates_straddling_and_partial_hours() -> None:
    """Prove a 30-minute window takes half of the last full hour plus the elapsed part of the current one."""
    previous, current = OFF_PEAK_HOUR - 3600, OFF_PEAK_HOUR
    costs = [(previous, 6.0), (current, 3.0)]
    spend = window_usd(costs, start=current + 900 - 1800, end=current + 900)
    check_close(spend, 6.0 * 900 / 3600 + 3.0, "a quarter of the previous hour and the whole elapsed quarter")


def test_balance_rows_and_keys_never_carry_secrets(tmp_path: Path) -> None:
    """Prove the exporter reads only private owner keys, dedupes them and writes numbers only."""
    for owner, mode in (("a", 0o600), ("b", 0o600), ("c", 0o644)):
        path = tmp_path / owner / "api-key"
        path.parent.mkdir()
        path.write_text(PLANTED_KEY_TEXT + ("-other" if owner == "c" else "") + "\n", encoding="ascii")
        path.chmod(mode)
    check_equal(owner_keys(tmp_path), [PLANTED_KEY_TEXT], "one shared private key; world-readable keys are refused")
    row = balance_row({
        "is_available": False,
        "balance_infos": [
            {"currency": "CNY", "total_balance": "9.00", "granted_balance": "0", "topped_up_balance": "9.00"},
            {"currency": "USD", "total_balance": "-0.00", "granted_balance": "0.00", "topped_up_balance": "-0.00"},
        ],
    })
    summary = (row.get("currency"), row.get("total_balance"), row.get("is_available"))
    check_equal(summary, ("USD", 0.0, False), "the USD row, with negative zero normalised")
    check(PLANTED_KEY_TEXT not in json.dumps(row), "no key in the row")


def _ledger(path: Path, hours: list[tuple[float, int, int, int]]) -> None:
    with closing(connect_fleet(path)) as connection:
        for hour, inputs, cached, outputs in hours:
            connection.execute(
                "INSERT INTO token_usage_hourly VALUES (?, 'master', '', 'p', 'a', 'deepseek', 'deepseek-flash', "
                "'deepseek', 'P', ?, ?, ?, 0, ?, 1, ?)",
                (int(hour), inputs, cached, outputs, inputs + outputs, NOW),
            )
        connection.commit()


def _first(payload: JsonObject) -> JsonObject:
    results = payload.get("results")
    return require_object(results[0] if isinstance(results, list) else None, description="first result")


def test_burn_factor_divides_projected_spend_by_the_balance(tmp_path: Path) -> None:
    """Prove a $10 balance against $1/h of ledger spend gives factor 2.4 over 24 hours."""
    ledger = tmp_path / "ledger.sqlite3"
    _ledger(ledger, [(OFF_PEAK_HOUR - 3600, 0, 0, MILLION), (OFF_PEAK_HOUR + 3600, 0, 0, MILLION * 5 // 6)])
    snapshot: JsonObject = {"generated_at": NOW, "total_balance": 10.0, "is_available": True, "keys": 1}
    (tmp_path / "deepseek-balance.json").write_text(json.dumps(snapshot), encoding="utf-8")
    payload = build_deepseek_burn(parse_pairs("30m:24h"), data_dir=tmp_path, ledger=ledger, now=NOW)
    result = _first(payload)
    check_close(optional_object(result.get("burn")).get("usd_per_hour"), 1.0, "one dollar per hour")
    check_close(result.get("factor"), 2.4, "24 dollars needed against 10 available")
    check_equal(result.get("status"), "short", "more spend than balance is a shortage")
    check_close(result.get("runway_hours"), 10.0, "ten hours of runway")
    check(optional_object(payload.get("balance")).get("stale") is False, "a fresh balance")


def test_empty_balance_is_short_and_reports_the_recent_pace(tmp_path: Path) -> None:
    """Prove an empty account is a shortage even without current spend, with the 7-day pace for a top-up."""
    ledger = tmp_path / "ledger.sqlite3"
    _ledger(ledger, [(OFF_PEAK_HOUR - 2 * 86_400, 0, 0, MILLION * 168 * 10 // 6)])
    snapshot: JsonObject = {"generated_at": NOW, "total_balance": 0.0, "is_available": False, "keys": 1}
    (tmp_path / "deepseek-balance.json").write_text(json.dumps(snapshot), encoding="utf-8")
    result = _first(build_deepseek_burn(parse_pairs("30m:24h"), data_dir=tmp_path, ledger=ledger, now=NOW))
    check_equal((result.get("status"), result.get("factor")), ("short", None), "an empty balance cannot serve")
    typical = optional_object(result.get("typical"))
    check_close(typical.get("usd_per_hour"), 1.0, "the 7-day pace is one dollar per hour")
    check_close(typical.get("demand_usd"), 24.0, "a top-up of 24 dollars covers the next day")


def test_missing_balance_is_unknown(tmp_path: Path) -> None:
    """Prove the factor is unknown until the exporter has written a balance."""
    result = _first(build_deepseek_burn(parse_pairs("24h:6d"), data_dir=tmp_path, ledger=tmp_path / "none", now=NOW))
    check_equal(result.get("status"), "unknown", "no balance yet")
