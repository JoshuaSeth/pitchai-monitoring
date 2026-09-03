# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed fixtures for aggregate scheduling-capacity tests."""

from __future__ import annotations

import secrets
from copy import deepcopy
from typing import TYPE_CHECKING, final

from .settings import DashboardSettings

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject


@final
class StaticCapacityService:
    """Serve one immutable operator snapshot through the dashboard lifespan."""

    _snapshot: JsonObject
    started: bool
    stopped: bool

    def __init__(self, snapshot: JsonObject) -> None:
        self._snapshot = snapshot
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        """Record dashboard startup."""
        self.started = True

    async def stop(self) -> None:
        """Record dashboard shutdown."""
        self.stopped = True

    async def snapshot(self) -> JsonObject:
        """Return an isolated copy of the aggregate source fixture."""
        return deepcopy(self._snapshot)


def dashboard_settings(root: Path) -> DashboardSettings:
    """Create non-probing settings for an isolated endpoint test.

    Returns:
        Dashboard settings without external IO or history persistence.
    """
    return DashboardSettings(
        broker_data_dir=root,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token=secrets.token_hex(16),
        safe_probe_enabled=False,
        probe_on_startup=False,
        snapshot_refresh_seconds=300,
        stale_after_seconds=600,
        require_proxy_auth=True,
        history_file=None,
    )


def operator_snapshot() -> JsonObject:
    """Return operator telemetry containing identities that must be removed.

    Returns:
        Complete dashboard data for two standard accounts and one protected account.
    """
    return {
        "generated_at": "2026-08-28T12:00:00Z",
        "source": {
            "stale": False,
            "stale_account_count": 0,
            "analytics_stale_account_count": 0,
            "error": None,
            "history_error": None,
            "newest_account_probe_at": "2026-08-28T11:59:30Z",
        },
        "summary": {
            "usable_now": 2,
            "capacity_basis": {
                "key": "five_hour",
                "label": "Five-hour",
                "reporting_accounts": 2,
                "eligible_accounts": 2,
                "measurement_status": "complete",
            },
            "window_aggregates": {
                "five_hour": {
                    "remaining_points": 125.5,
                    "maximum_known_points": 200.0,
                    "remaining_percent": 62.8,
                },
            },
        },
        "usage_history": {
            "summary": {
                "trailing_two_hour_tokens": 42_000,
                "average_hourly_tokens": 18_000,
                "observed_share_percent": 81.5,
            },
        },
        "runout_forecast": {
            "data_available": True,
            "highest_risk": "medium",
            "highest_probability_percent": 31,
            "burn_rate": {
                "capacity_points_per_hour": 12.5,
                "confidence": "high",
                "source": "native_broker_samples",
                "lookback_hours": 2,
                "sample_count": 20,
                "covered_accounts": 2,
                "coefficient_of_variation": 0.2,
            },
            "horizons": [
                {
                    "key": "hour",
                    "horizon_seconds": 3600,
                    "probability_percent": 0,
                    "risk": "low",
                    "expected_runout_at": None,
                    "scheduled_resets": 1,
                    "scheduled_capacity_points": 100,
                    "driver_with_identity": "must not escape",
                },
            ],
        },
        "reset_bank": {"total_available": 3, "details": ["must not escape"]},
        "accounts": [_account_one(), _account_two(), _protected_account()],
    }


def routing_inventory() -> list[JsonObject]:
    """Return raw metadata used to verify the account routing-tier join.

    Returns:
        Inventory rows for every account in :func:`operator_snapshot`.
    """
    return [
        {"metadata": {"label": "private-one@pitchai.net", "last_resort": False}},
        {"metadata": {"label": "private-two@pitchai.net", "last_resort": False}},
        {"metadata": {"label": "private-reserve@pitchai.net", "last_resort": True}},
    ]


def _account_one() -> JsonObject:
    """Return one currently selectable measured account."""
    return {
        "label": "private-one@pitchai.net",
        "email": "private-one@pitchai.net",
        "enabled": True,
        "last_resort": False,
        "auth_valid": True,
        "stale": False,
        "selectable_now": True,
        "status": "available",
        "five_hour": _window(75.5, "2026-08-28T13:00:00Z", 18_000),
        "weekly": _window(80.0, "2026-09-03T13:00:00Z", 604_800),
    }


def _account_two() -> JsonObject:
    """Return one currently limited measured account."""
    return {
        "label": "private-two@pitchai.net",
        "email": "private-two@pitchai.net",
        "enabled": True,
        "last_resort": False,
        "auth_valid": True,
        "stale": False,
        "selectable_now": False,
        "status": "five_hour_limited",
        "five_hour": _window(50.0, "2026-08-28T13:00:00Z", 18_000),
        "weekly": _window(70.0, "2026-09-03T13:00:00Z", 604_800),
    }


def _protected_account() -> JsonObject:
    """Return one currently selectable protected account."""
    return {
        "label": "private-reserve@pitchai.net",
        "email": "private-reserve@pitchai.net",
        "enabled": True,
        "last_resort": True,
        "auth_valid": True,
        "stale": False,
        "selectable_now": True,
        "status": "available",
        "five_hour": _window(88.0, "2026-08-28T13:00:00Z", 18_000),
        "weekly": _window(90.0, "2026-09-03T13:00:00Z", 604_800),
    }


def _window(remaining: float, reset_at: str, window_seconds: int) -> JsonObject:
    """Return one reported provider capacity window."""
    return {
        "reported": True,
        "remaining_percent": remaining,
        "reset_at": reset_at,
        "window_seconds": window_seconds,
    }
