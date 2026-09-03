# Copyright (c) 2026 PitchAI. All rights reserved.
"""Standard-tier routing and burn proof for scheduling-capacity schema three."""

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

_STANDARD_BURN_POINTS_PER_HOUR = 12.0


@final
class SchedulingCapacityV3Test(UsageTimeSeriesCase):
    """Prove protected capacity never enters ordinary priority admission."""

    @staticmethod
    def test_raw_inventory_excludes_protected_capacity_and_burn() -> None:
        """Use only standard-tier points and native samples for admission math."""
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
            payload.get("methodology"), description="methodology",
        )
        check_equal(capacity.get("eligible_accounts"), 2, "standard eligible accounts")
        check_close(capacity.get("remaining_points"), 75.5, "standard usable points")
        check_close(
            capacity.get("maximum_known_points"), 200.0, "standard maximum points",
        )
        check_close(
            burn.get("capacity_points_per_hour"),
            _STANDARD_BURN_POINTS_PER_HOUR,
            "standard-only burn rate",
        )
        check_equal(protected.get("account_count"), 1, "protected account count")
        check_equal(
            protected.get("usable_accounts_now"), 1, "protected usable accounts",
        )
        check_close(
            protected.get("remaining_points"), 88.0, "protected remaining points",
        )
        check(
            protected.get("included_in_admission") is False,
            "protected capacity entered admission",
        )
        check_equal(
            methodology.get("routing_tier_scope"),
            "standard_only",
            "routing-tier scope",
        )
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
        check_equal(first_reset.get("count"), 2, "standard account reset count")
        check_close(first_reset.get("capacity_points"), 200.0, "standard reset points")
        check_equal(
            first_reset.get("restores_selectability_count"),
            1,
            "restoring account count",
        )

    @staticmethod
    def test_inventory_mismatch_fails_closed() -> None:
        """Reject incomplete routing evidence instead of counting an unknown tier.

        Raises:
            AssertionError: If incomplete evidence does not fail with the expected reason.
        """
        incomplete = routing_inventory()[:-1]
        try:
            build_scheduling_capacity_snapshot(
                operator_snapshot(),
                raw_accounts=incomplete,
                usage_samples=_mixed_routing_samples(),
            )
        except ValueError as error:
            check("does not match" in str(error), "inventory failure lost its reason")
        else:
            message = "incomplete routing inventory did not fail closed"
            raise AssertionError(message)

    @staticmethod
    def test_disabled_and_auth_invalid_accounts_do_not_change_standard_scope() -> None:
        """Exclude non-routable identities while retaining rate-limited capacity."""
        snapshot = operator_snapshot()
        accounts = require_array(snapshot.get("accounts"), "accounts")
        disabled = _non_routable_account(
            "private-disabled@pitchai.net", auth_valid=True, enabled=False,
        )
        invalid = _non_routable_account(
            "private-invalid@pitchai.net", auth_valid=False, enabled=True,
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
        check_equal(capacity.get("eligible_accounts"), 2, "eligible standard accounts")
        check_equal(
            capacity.get("reporting_accounts"), 2, "reporting standard accounts",
        )


def _mixed_routing_samples() -> list[JsonObject]:
    samples: list[JsonObject] = []
    for offset, minute in enumerate((50, 55, 0)):
        hour = 11 if minute else 12
        samples.append(
            {
                "at": f"2026-08-28T{hour:02d}:{minute:02d}:00+00:00",
                "accounts": {
                    "private-one@pitchai.net": _sample_window(float(offset)),
                    "private-two@pitchai.net": _sample_window(50.0),
                    "private-reserve@pitchai.net": _sample_window(float(offset * 10)),
                },
            },
        )
    return samples


def _sample_window(used_percent: float) -> JsonObject:
    return {
        "five_used_percent": used_percent,
        "five_reset_at": "2026-08-28T13:00:00+00:00",
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
