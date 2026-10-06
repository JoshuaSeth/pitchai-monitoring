# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the compact native burn-factor projection."""

from __future__ import annotations

import json

from ._timeseries_test_fixtures import check, check_equal
from .mobile_burn_factors import project_pool, project_result
from .timeseries_types import require_object

PRIVATE_EMAIL = "private-account@example.com"


def test_points_and_money_results_keep_only_rendered_fields() -> None:
    """Prove points pools map capacity fields and the DeepSeek pool maps dollar fields."""
    points = project_result(
        {
            "rolling": "24h",
            "horizon": "6d",
            "factor": 0.34,
            "status": "good",
            "lower_bound": True,
            "margin_points": 276.0,
            "demand_points": 140.0,
            "burn": {"points_per_hour": 1.0},
            "capacity": {"effective_points": 416.0, "blocked_until": None, "accounts": [PRIVATE_EMAIL]},
        },
        money=False,
    )
    check_equal((points.get("factor"), points.get("available"), points.get("margin")), (0.34, 416.0, 276.0), "points")
    check(PRIVATE_EMAIL not in json.dumps(points), "no account detail leaves the server")
    money = project_pool(
        "deepseek",
        "DeepSeek",
        {
            "unit": "usd",
            "balance": {"total_usd": 0.0},
            "results": [{"status": "short", "demand_usd": 164.63, "burn": {"usd_per_hour": 1.14}}],
        },
    )
    check_equal((money.get("unit"), money.get("balance_usd")), ("usd", 0.0), "the DeepSeek pool is money")
    results = money.get("results")
    first = require_object(results[0] if isinstance(results, list) else None, description="money result")
    check_equal((first.get("demand"), first.get("burn_per_hour")), (164.63, 1.14), "dollar fields are mapped")
