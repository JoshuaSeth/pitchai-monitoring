# Copyright (c) 2026 PitchAI. All rights reserved.
"""Money burn factor for the prepaid DeepSeek API account.

DeepSeek is billed per token from one prepaid balance, so capacity is the
balance itself and burn is spend per hour. Spend is estimated from the fleet
token ledger (every ``deepseek-*`` model turn, whichever owner ran it) at the
engine's published price snapshot, including DeepSeek's weekday peak doubling.
Factor = burn per hour x horizon / balance; below 1 the balance outlasts the
horizon at this pace.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing, suppress
from typing import TYPE_CHECKING, cast

from .burn_factor_results import GOOD_BELOW, SHORT_FROM
from .claude_accounts import load_json_object
from .timeseries_types import number_value
from .token_ledger.fleet_store import connect_fleet

if TYPE_CHECKING:
    from pathlib import Path

    from .burn_factor_windows import WindowPair
    from .timeseries_types import JsonObject

PRICE_SNAPSHOT = "deepseek-flash-2026-09-16"
PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
CACHED_RATE, UNCACHED_RATE, OUTPUT_RATE = 0.003, 0.15, 0.60
PEAK_HOURS = ((1, 4), (6, 10))
TYPICAL_DAYS = 7
BALANCE_FRESH_SECONDS = 900.0
RUNWAY_LIMIT_HOURS = 14 * 24.0
_HOUR, _MILLION, _WEEKDAYS = 3600.0, 1_000_000.0, 5
_QUERY = (
    "SELECT hour_epoch, SUM(input), SUM(cached_input), SUM(output) FROM token_usage_hourly "
    "WHERE provider = 'deepseek' AND hour_epoch >= ? GROUP BY hour_epoch"
)
_AS_OF_QUERY = "SELECT MAX(received_at) FROM token_usage_hourly"


def hour_cost(hour_epoch: float, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """Return the USD cost of one ledger hour, doubled inside DeepSeek's weekday peak hours (UTC)."""
    moment = time.gmtime(hour_epoch)
    peak = moment.tm_wday < _WEEKDAYS and any(start <= moment.tm_hour < end for start, end in PEAK_HOURS)
    uncached = max(0, input_tokens - cached_tokens)
    base = (cached_tokens * CACHED_RATE + uncached * UNCACHED_RATE + output_tokens * OUTPUT_RATE) / _MILLION
    return base * (2.0 if peak else 1.0)


def ledger_costs(path: Path, *, since: float) -> tuple[list[tuple[float, float]], float | None]:
    """Return ``(hour_epoch, usd)`` per DeepSeek ledger hour since ``since`` and the ledger's last delivery."""
    rows: list[tuple[int, int, int, int]] = []
    as_of: float | None = None
    with suppress(sqlite3.Error), closing(connect_fleet(path, read_only=True)) as connection:
        cursor = connection.execute(_QUERY, (int(since - _HOUR),))
        rows = cast("list[tuple[int, int, int, int]]", cursor.fetchall())
        latest = cast("tuple[float | None]", connection.execute(_AS_OF_QUERY).fetchone())
        as_of = latest[0]
    costs = [(float(hour), hour_cost(hour, inputs, cached, outputs)) for hour, inputs, cached, outputs in rows]
    return costs, as_of


def window_usd(costs: list[tuple[float, float]], *, start: float, end: float) -> float:
    """Return the spend inside ``[start, end]``, prorating the hourly buckets that straddle it."""
    total = 0.0
    for hour, usd in costs:
        bucket_end = min(hour + _HOUR, end)
        covered = bucket_end - max(hour, start)
        if bucket_end > hour and covered > 0:
            total += usd * covered / (bucket_end - hour)
    return total


def _status(factor: float | None) -> str:
    if factor is None or factor >= SHORT_FROM:
        return "short"
    return "good" if factor < GOOD_BELOW else "tight"


def pair_result(
    pair: WindowPair,
    costs: list[tuple[float, float]],
    *,
    as_of: float,
    balance: float | None,
) -> JsonObject:
    """Return the factor, runway and money breakdown of one rolling window and horizon."""
    rate = window_usd(costs, start=as_of - pair.rolling_seconds, end=as_of) * _HOUR / pair.rolling_seconds
    typical = window_usd(costs, start=as_of - TYPICAL_DAYS * 86_400, end=as_of) / (TYPICAL_DAYS * 24)
    horizon_hours = pair.horizon_seconds / _HOUR
    demand = rate * horizon_hours
    result: JsonObject = {
        "rolling": pair.rolling,
        "horizon": pair.horizon,
        "rolling_seconds": pair.rolling_seconds,
        "horizon_seconds": pair.horizon_seconds,
        "burn": {"usd_per_hour": round(rate, 4), "source": "token_ledger_estimate", "price_snapshot": PRICE_SNAPSHOT},
        "typical": {
            "days": TYPICAL_DAYS,
            "usd_per_hour": round(typical, 4),
            "demand_usd": round(typical * horizon_hours, 2),
        },
        "demand_usd": round(demand, 2),
    }
    if balance is None:
        reason = "The DeepSeek balance has not been exported yet."
        return {**result, "factor": None, "status": "unknown", "reason": reason}
    factor = demand / balance if balance > 0 else None
    runway = balance / rate if rate > 0 else None
    return {
        **result,
        "factor": None if factor is None else round(factor, 3),
        "status": _status(factor),
        "available_usd": round(balance, 2),
        "margin_usd": round(balance - demand, 2),
        "runway_hours": None if runway is None or runway > RUNWAY_LIMIT_HOURS else round(runway, 2),
        "reason": None,
    }


def _balance(snapshot: JsonObject, now: float) -> JsonObject:
    generated = number_value(snapshot.get("generated_at"))
    return {
        "total_usd": number_value(snapshot.get("total_balance")),
        "granted_usd": number_value(snapshot.get("granted_balance")),
        "topped_up_usd": number_value(snapshot.get("topped_up_balance")),
        "currency": snapshot.get("currency"),
        "is_available": snapshot.get("is_available") is True,
        "keys": snapshot.get("keys"),
        "observed_at": generated,
        "stale": generated is None or not 0 <= now - generated <= BALANCE_FRESH_SECONDS,
    }


def build_deepseek_burn(
    pairs: list[WindowPair],
    *,
    data_dir: Path,
    ledger: Path,
    now: float | None = None,
) -> JsonObject:
    """Return the DeepSeek balance, price snapshot and one money burn-factor result per pair."""
    current = time.time() if now is None else now
    longest = max([pair.rolling_seconds for pair in pairs] + [TYPICAL_DAYS * 86_400])
    costs, delivered = ledger_costs(ledger, since=current - longest)
    as_of = min(current, delivered) if delivered is not None else current
    balance = _balance(load_json_object(data_dir / "deepseek-balance.json") or {}, current)
    total = number_value(balance.get("total_usd"))
    return {
        "schema_version": 1,
        "generated_at": current,
        "unit": "usd",
        "basis": {"key": "usd", "label": "USD balance"},
        "balance": balance,
        "price": {"snapshot": PRICE_SNAPSHOT, "source": PRICE_SOURCE, "peak": "x2 weekdays 01-04 and 06-10 UTC"},
        "ledger_as_of": as_of,
        "results": [pair_result(pair, costs, as_of=as_of, balance=total) for pair in pairs],
    }
