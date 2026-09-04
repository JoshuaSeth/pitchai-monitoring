# Copyright (c) 2026 PitchAI. All rights reserved.
"""Small redacted projections used by the scheduling-capacity contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .scheduling_capacity_values import burn_confidence, runout_risk
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    optional_object,
    text_value,
)

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue


def burn_projection(runout: JsonObject) -> JsonObject:
    """Project aggregate capacity burn without account identity."""
    burn = optional_object(runout.get("burn_rate"))
    return {
        "capacity_points_per_hour": number_value(burn.get("capacity_points_per_hour")),
        "confidence": burn_confidence(burn.get("confidence")),
        "source": text_value(burn.get("source")),
        "lookback_hours": number_value(burn.get("lookback_hours")),
        "sample_count": nonnegative_integer(burn.get("sample_count")),
        "covered_accounts": nonnegative_integer(burn.get("covered_accounts")),
        "coefficient_of_variation": number_value(burn.get("coefficient_of_variation")),
    }


def token_burn_projection(token_summary: JsonObject) -> JsonObject:
    """Project provider tokens for aggregate attribution diagnostics."""
    return {
        "trailing_two_hour_tokens": nonnegative_integer(
            token_summary.get("trailing_two_hour_tokens"),
        ),
        "average_hourly_tokens": nonnegative_integer(
            token_summary.get("average_hourly_tokens"),
        ),
        "observed_share_percent": number_value(
            token_summary.get("observed_share_percent"),
        ),
        "diagnostic_only": True,
    }


def banked_reset_projection(raw_reset_bank: JsonValue) -> JsonObject:
    """Exclude manual reset credits from automatic capacity."""
    reset_bank = optional_object(raw_reset_bank)
    return {
        "available_count": nonnegative_integer(reset_bank.get("total_available")),
        "included_as_automatic_capacity": False,
    }


def redacted_runout_horizons(raw_horizons: JsonValue) -> list[JsonValue]:
    """Return scheduler-relevant runout horizons without driver identities."""
    horizons: list[JsonValue] = []
    if not isinstance(raw_horizons, list):
        return horizons
    for raw_horizon in raw_horizons:
        horizon = optional_object(raw_horizon)
        key = text_value(horizon.get("key"))
        if key not in {"hour", "six_hours", "day"}:
            continue
        horizons.append(
            {
                "key": key,
                "horizon_seconds": nonnegative_integer(horizon.get("horizon_seconds")),
                "probability_percent": number_value(horizon.get("probability_percent")),
                "risk": runout_risk(horizon.get("risk")),
                "expected_runout_at": text_value(horizon.get("expected_runout_at")),
                "scheduled_resets": nonnegative_integer(
                    horizon.get("scheduled_resets"),
                ),
                "scheduled_capacity_points": number_value(
                    horizon.get("scheduled_capacity_points"),
                ),
            },
        )
    return horizons
