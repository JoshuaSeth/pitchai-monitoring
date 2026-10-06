# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compact, account-free burn factors for the iPhone app, the Watch and its complications.

Every pool is answered for the dashboard's two default views (30 minutes of burn
against the next 24 hours, a day of burn against the next 6 days). Only pool
aggregates leave the server: no account label, email or key.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .burn_factor_windows import DEFAULT_PAIRS, parse_pairs
from .history import isoformat
from .timeseries_types import number_value, optional_object, text_value

if TYPE_CHECKING:
    from .burn_factor_routes import BurnFactorCache
    from .timeseries_types import JsonObject, JsonValue

MOBILE_POOLS = (("openai", "Codex"), ("anthropic", "Claude"), ("opencode", "OpenCode"), ("deepseek", "DeepSeek"))
_MONEY = "usd"


def project_result(result: JsonObject, *, money: bool) -> JsonObject:
    """Return the fields a native client renders for one rolling window and horizon."""
    burn = optional_object(result.get("burn"))
    capacity = optional_object(result.get("capacity"))
    available = result.get("available_usd") if money else capacity.get("effective_points")
    return {
        "rolling": text_value(result.get("rolling")),
        "horizon": text_value(result.get("horizon")),
        "factor": number_value(result.get("factor")),
        "status": text_value(result.get("status")) or "unknown",
        "lower_bound": result.get("lower_bound") is True,
        "runway_hours": number_value(result.get("runway_hours")),
        "burn_per_hour": number_value(burn.get("usd_per_hour" if money else "points_per_hour")),
        "demand": number_value(result.get("demand_usd" if money else "demand_points")),
        "available": number_value(available),
        "margin": number_value(result.get("margin_usd" if money else "margin_points")),
        "blocked_until": text_value(capacity.get("blocked_until")),
    }


def project_pool(key: str, label: str, payload: JsonObject) -> JsonObject:
    """Return one pool's unit, balance and projected results."""
    money = payload.get("unit") == _MONEY
    balance = optional_object(payload.get("balance"))
    raw_results = payload.get("results")
    raw_list = raw_results if isinstance(raw_results, list) else []
    results: list[JsonValue] = [project_result(optional_object(raw), money=money) for raw in raw_list]
    return {
        "key": key,
        "label": label,
        "unit": _MONEY if money else "points",
        "balance_usd": number_value(balance.get("total_usd")) if money else None,
        "results": results,
    }


async def build_mobile_burn_factors(cache: BurnFactorCache, *, now: float | None = None) -> JsonObject:
    """Return every pool's two default burn-factor views from the shared 30-second cache."""
    pairs = parse_pairs(DEFAULT_PAIRS)
    pools: list[JsonValue] = []
    for key, label in MOBILE_POOLS:
        payload = await cache.payload(key, pairs)
        pools.append(project_pool(key, label, payload))
    moment = datetime.fromtimestamp(time.time() if now is None else now, UTC)
    return {"schema_version": 1, "generated_at": isoformat(moment), "pools": pools}
