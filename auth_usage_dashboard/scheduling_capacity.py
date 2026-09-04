# Copyright (c) 2026 PitchAI. All rights reserved.
"""Aggregate-only scheduling-capacity contract for the queue drainer."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .history import capacity_burn_window
from .scheduling_capacity_scope import scheduling_capacity_scope
from .scheduling_capacity_timeline import scheduling_capacity_timeline
from .scheduling_capacity_timeline_values import aware_datetime
from .scheduling_capacity_values import (
    burn_confidence,
    freshness_seconds,
    measurement_status,
    runout_risk,
)
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    optional_object,
    text_value,
)

if TYPE_CHECKING:
    from .scheduling_capacity_timeline import SchedulingCapacityTimeline
    from .timeseries_types import JsonObject, JsonValue

SCHEDULING_CAPACITY_SCHEMA_VERSION = 4


def build_scheduling_capacity_snapshot(
    dashboard_snapshot: JsonObject,
    *,
    raw_accounts: list[JsonObject] | None = None,
    usage_samples: list[JsonObject] | None = None,
) -> JsonObject:
    """Project the operator snapshot into a redacted scheduler contract.

    Returns:
        Versioned aggregate scheduling-capacity data.
    """
    generated_at = text_value(dashboard_snapshot.get("generated_at"))
    scope = scheduling_capacity_scope(
        dashboard_snapshot,
        raw_accounts=raw_accounts,
        usage_samples=usage_samples,
    )
    summary = scope.summary
    source = scope.source
    runout = scope.runout
    basis_key = _basis_key(summary)
    timeline = scheduling_capacity_timeline(
        list(scope.burnable_accounts),
        basis_key=basis_key,
        generated_at=generated_at,
    )
    source_projection = _source_projection(source, generated_at=generated_at)
    status, capacity = _capacity_projection(
        summary,
        source_projection,
        timeline=timeline,
    )
    token_summary = optional_object(
        optional_object(dashboard_snapshot.get("usage_history")).get("summary"),
    )
    observed_at = aware_datetime(generated_at)
    if observed_at is None:
        message = "operator scheduling snapshot has an invalid generated timestamp"
        raise ValueError(message)
    burn_windows: JsonObject = {
        "last_hour": cast(
            "JsonObject",
            cast(
                "object",
                capacity_burn_window(
                    list(scope.burnable_accounts),
                    samples=usage_samples or [],
                    now=observed_at,
                    window_hours=1,
                    window_key=basis_key or "five_hour",
                ),
            ),
        ),
        "last_24_hours": cast(
            "JsonObject",
            cast(
                "object",
                capacity_burn_window(
                    list(scope.burnable_accounts),
                    samples=usage_samples or [],
                    now=observed_at,
                    window_hours=24,
                    window_key=basis_key or "five_hour",
                ),
            ),
        ),
    }

    payload: JsonObject = {
        "schema_version": SCHEDULING_CAPACITY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "source": source_projection,
        "capacity": capacity,
        "protected_last_resort": scope.protected_capacity,
        "burn": _burn_projection(runout),
        "burn_windows": burn_windows,
        "token_burn": _token_burn_projection(token_summary),
        "expiry_buckets": timeline.expiry_buckets,
        "automatic_resets": timeline.automatic_resets,
        "runout": {
            "data_available": runout.get("data_available") is True,
            "highest_risk": runout_risk(runout.get("highest_risk")),
            "highest_probability_percent": number_value(
                runout.get("highest_probability_percent"),
            ),
            "horizons": _redacted_runout_horizons(runout.get("horizons")),
        },
        "banked_resets": _banked_reset_projection(dashboard_snapshot.get("reset_bank")),
        "methodology": {
            "unit": "normalized reported-window capacity point",
            "identity_scope": "aggregate_only",
            "routing_tier_scope": "broker_burnable",
            "protected_capacity_policy": "broker_routes_last",
            "account_ordering_owner": "authentication_broker",
            "banked_reset_policy": "excluded_until_explicitly_redeemed",
            "token_usage_role": "project_attribution_denominator",
        },
    }
    return payload


def _basis_key(summary: JsonObject) -> str | None:
    basis = optional_object(summary.get("capacity_basis"))
    value = basis.get("key")
    return (
        value if isinstance(value, str) and value in {"five_hour", "weekly"} else None
    )


def _source_projection(source: JsonObject, *, generated_at: str | None) -> JsonObject:
    newest_probe_at = text_value(source.get("newest_account_probe_at"))
    return {
        "stale": _scheduling_source_stale(source),
        "error": text_value(source.get("error")),
        "history_error": text_value(source.get("history_error")),
        "newest_probe_at": newest_probe_at,
        "freshness_seconds": freshness_seconds(generated_at, newest_probe_at),
    }


def _scheduling_source_stale(source: JsonObject) -> bool:
    """Keep capacity fail-closed without coupling it to diagnostic analytics.

    Returns:
        Whether scheduler-relevant capacity evidence is stale.
    """
    if source.get("error") is not None:
        return True
    stale_account_count = nonnegative_integer(source.get("stale_account_count"))
    if stale_account_count is None:
        return source.get("stale") is True
    return stale_account_count > 0


def _burn_projection(runout: JsonObject) -> JsonObject:
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


def _token_burn_projection(token_summary: JsonObject) -> JsonObject:
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


def _banked_reset_projection(raw_reset_bank: JsonValue) -> JsonObject:
    reset_bank = optional_object(raw_reset_bank)
    return {
        "available_count": nonnegative_integer(reset_bank.get("total_available")),
        "included_as_automatic_capacity": False,
    }


def _capacity_projection(
    summary: JsonObject,
    source: JsonObject,
    *,
    timeline: SchedulingCapacityTimeline,
) -> tuple[str, JsonObject]:
    """Return availability status and normalized capacity fields."""
    basis = optional_object(summary.get("capacity_basis"))
    raw_basis_key = basis.get("key")
    basis_key = (
        raw_basis_key
        if isinstance(raw_basis_key, str) and raw_basis_key in {"five_hour", "weekly"}
        else None
    )
    aggregates = optional_object(summary.get("window_aggregates"))
    aggregate: JsonObject = (
        optional_object(aggregates.get(basis_key)) if basis_key is not None else {}
    )
    remaining_points = timeline.current_points
    normalized_status = measurement_status(basis.get("measurement_status"))
    if basis_key is None or remaining_points is None:
        status = "unavailable"
    elif (
        source.get("stale") is True
        or normalized_status != "complete"
        or timeline.status != "complete"
    ):
        status = "degraded"
    else:
        status = "available"

    capacity: JsonObject = {
        "basis_key": basis_key,
        "basis_label": text_value(basis.get("label")),
        "measurement_status": normalized_status,
        "timeline_status": timeline.status,
        "remaining_points": remaining_points,
        "maximum_known_points": number_value(aggregate.get("maximum_known_points")),
        "remaining_percent": _usable_remaining_percent(
            remaining_points,
            number_value(aggregate.get("maximum_known_points")),
        ),
        "reporting_accounts": nonnegative_integer(basis.get("reporting_accounts")),
        "eligible_accounts": nonnegative_integer(basis.get("eligible_accounts")),
        "usable_accounts_now": nonnegative_integer(summary.get("usable_now")),
    }
    return status, capacity


def _usable_remaining_percent(
    remaining_points: float | None,
    maximum_points: float | None,
) -> float | None:
    if remaining_points is None or maximum_points is None or maximum_points <= 0.0:
        return None
    return round(remaining_points / maximum_points * 100.0, 1)


def _redacted_runout_horizons(raw_horizons: JsonValue) -> list[JsonValue]:
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
