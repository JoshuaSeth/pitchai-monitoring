# Copyright (c) 2026 PitchAI. All rights reserved.
"""Broker-owned routing and burn proof for scheduling-capacity schema four."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from ._scheduling_capacity_test_fixtures import operator_snapshot, routing_inventory
from ._timeseries_test_fixtures import (
    UsageTimeSeriesCase,
    check,
    check_close,
    check_equal,
    require_array,
)
from .scheduling_capacity import build_scheduling_capacity_snapshot
from .scheduling_capacity_check import validate_scheduling_capacity_payload
from .timeseries_types import require_object

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

_BURNABLE_POINTS_PER_HOUR = 132.0


@final
class SchedulingCapacityV4Test(UsageTimeSeriesCase):
    """Prove routing metadata cannot suppress broker-burnable capacity."""

    @staticmethod
    def test_raw_inventory_includes_all_burnable_capacity_and_burn() -> None:
        """Include protected capacity while leaving its ordering to the broker."""
        payload = build_scheduling_capacity_snapshot(
            operator_snapshot(),
            raw_accounts=routing_inventory(),
            usage_samples=_mixed_routing_samples(),
        )

        capacity = require_object(payload.get("capacity"), description="capacity")
        burn = require_object(payload.get("burn"), description="burn")
        protected = require_object(
            payload.get("protected_last_resort"),
            description="protected capacity",
        )
        methodology = require_object(
            payload.get("methodology"),
            description="methodology",
        )
        check_equal(capacity.get("eligible_accounts"), 3, "burnable eligible accounts")
        check_close(capacity.get("remaining_points"), 163.5, "burnable usable points")
        check_close(
            capacity.get("maximum_known_points"),
            300.0,
            "burnable maximum points",
        )
        check_close(
            burn.get("capacity_points_per_hour"),
            _BURNABLE_POINTS_PER_HOUR,
            "broker-burnable burn rate",
        )
        check_equal(protected.get("account_count"), 1, "protected account count")
        check_equal(
            protected.get("usable_accounts_now"),
            1,
            "protected usable accounts",
        )
        check_close(
            protected.get("remaining_points"),
            88.0,
            "protected remaining points",
        )
        check(
            protected.get("included_in_admission") is True,
            "protected capacity was omitted from admission math",
        )
        check_equal(
            protected.get("routing_owner"),
            "authentication_broker",
            "protected routing owner",
        )
        check_equal(
            methodology.get("routing_tier_scope"),
            "broker_burnable",
            "routing-tier scope",
        )
        windows = require_object(
            payload.get("burn_windows"), description="burn windows"
        )
        last_hour = require_object(windows.get("last_hour"), description="last hour")
        check_close(last_hour.get("capacity_points"), 22.0, "last-hour burn points")
        check_close(
            last_hour.get("capacity_points_per_hour"),
            _BURNABLE_POINTS_PER_HOUR,
            "last-hour burn rate",
        )
        check_equal(last_hour.get("provider_tokens"), 600, "last-hour provider tokens")
        check_close(last_hour.get("coverage_percent"), 16.7, "last-hour coverage")
        validate_scheduling_capacity_payload(payload)

    @staticmethod
    def test_rate_limited_standard_account_remains_in_reset_timeline() -> None:
        """Keep measured future capacity even when an account is not selectable now."""
        payload = build_scheduling_capacity_snapshot(
            operator_snapshot(),
            raw_accounts=routing_inventory(),
            usage_samples=_mixed_routing_samples(),
        )

        resets = require_array(payload.get("automatic_resets"), "automatic resets")
        first_reset = require_object(resets[0], description="first reset")
        check_equal(first_reset.get("count"), 3, "burnable account reset count")
        check_close(first_reset.get("capacity_points"), 300.0, "burnable reset points")
        check_equal(
            first_reset.get("restores_selectability_count"),
            1,
            "restoring account count",
        )

    @staticmethod
    def test_inventory_mismatch_is_informational_not_an_admission_gate() -> None:
        """Retain burnable capacity when protected classification is incomplete."""
        incomplete = routing_inventory()[:-1]
        payload = build_scheduling_capacity_snapshot(
            operator_snapshot(),
            raw_accounts=incomplete,
            usage_samples=_mixed_routing_samples(),
        )
        capacity = require_object(payload.get("capacity"), description="capacity")
        protected = require_object(
            payload.get("protected_last_resort"),
            description="protected capacity",
        )
        check_equal(capacity.get("eligible_accounts"), 3, "burnable accounts")
        check_close(capacity.get("remaining_points"), 163.5, "burnable points")
        check_equal(protected.get("classification_status"), "partial", "classification")
        check_equal(
            protected.get("unclassified_account_count"), 1, "unclassified count"
        )
        validate_scheduling_capacity_payload(payload)

    @staticmethod
    def test_disabled_and_auth_invalid_accounts_do_not_change_standard_scope() -> None:
        """Exclude non-routable identities while retaining rate-limited capacity."""
        snapshot = operator_snapshot()
        accounts = require_array(snapshot.get("accounts"), "accounts")
        disabled = _non_routable_account(
            "private-disabled@pitchai.net",
            auth_valid=True,
            enabled=False,
        )
        invalid = _non_routable_account(
            "private-invalid@pitchai.net",
            auth_valid=False,
            enabled=True,
        )
        accounts.extend((disabled, invalid))
        inventory = routing_inventory()
        inventory.extend(
            (
                {
                    "metadata": {
                        "label": "private-disabled@pitchai.net",
                        "last_resort": False,
                    },
                },
                {
                    "metadata": {
                        "label": "private-invalid@pitchai.net",
                        "last_resort": False,
                    },
                },
            ),
        )

        payload = build_scheduling_capacity_snapshot(
            snapshot,
            raw_accounts=inventory,
            usage_samples=_mixed_routing_samples(),
        )

        capacity = require_object(payload.get("capacity"), description="capacity")
        check_equal(capacity.get("eligible_accounts"), 3, "eligible burnable accounts")
        check_equal(
            capacity.get("reporting_accounts"),
            3,
            "reporting burnable accounts",
        )


def _mixed_routing_samples() -> list[JsonObject]:
    samples: list[JsonObject] = []
    for offset, minute in enumerate((50, 55, 0)):
        hour = 11 if minute else 12
        samples.append(
            {
                "at": f"2026-08-28T{hour:02d}:{minute:02d}:00+00:00",
                "accounts": {
                    "private-one@pitchai.net": _sample_window(
                        float(offset),
                        1_000 + offset * 100,
                    ),
                    "private-two@pitchai.net": _sample_window(50.0, 500),
                    "private-reserve@pitchai.net": _sample_window(
                        float(offset * 10),
                        2_000 + offset * 200,
                    ),
                },
            },
        )
    return samples


def _sample_window(used_percent: float, tokens_today: int) -> JsonObject:
    return {
        "five_used_percent": used_percent,
        "five_reset_at": "2026-08-28T13:00:00+00:00",
        "token_date": "2026-08-28",
        "tokens_today": tokens_today,
    }


def _non_routable_account(label: str, *, auth_valid: bool, enabled: bool) -> JsonObject:
    return {
        "label": label,
        "email": label,
        "enabled": enabled,
        "last_resort": False,
        "auth_valid": auth_valid,
        "stale": False,
        "selectable_now": False,
        "status": "disabled" if not enabled else "auth_invalid",
        "five_hour": {
            "reported": True,
            "remaining_percent": 100.0,
            "reset_at": "2026-08-28T13:00:00Z",
            "window_seconds": 18_000,
        },
        "weekly": {
            "reported": True,
            "remaining_percent": 100.0,
            "reset_at": "2026-09-03T13:00:00Z",
            "window_seconds": 604_800,
        },
    }
