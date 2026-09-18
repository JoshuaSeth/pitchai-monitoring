# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed fixtures shared by usage-history persistence tests."""

from __future__ import annotations

import math
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .timeseries_store import UsageTimeSeriesStore

if TYPE_CHECKING:
    from collections.abc import Generator

    from .timeseries_types import JsonObject, JsonValue

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SAMPLE_INTERVAL_SECONDS = 300
type TestCondition = bool


@contextmanager
def isolated_root() -> Generator[Path, None, None]:
    """Yield an automatically removed test directory."""
    with tempfile.TemporaryDirectory() as temporary_root:
        yield Path(temporary_root)


def check(condition: TestCondition, description: str) -> None:
    """Fail a test when one explicit condition is false.

    Raises:
        AssertionError: If the condition is false.
    """
    if not condition:
        raise AssertionError(description)


def check_equal[Value](actual: Value, expected: Value, description: str) -> None:
    """Fail a test when two typed values differ.

    Raises:
        AssertionError: If the values differ.
    """
    if actual != expected:
        message = f"{description}: expected {expected!r}, got {actual!r}"
        raise AssertionError(message)


def check_close(actual: JsonValue, expected: float, description: str) -> None:
    """Fail a test when one JSON number differs materially.

    Raises:
        AssertionError: If the numeric value is not close.
        TypeError: If the value is absent or non-numeric.
    """
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        message = f"{description}: expected numeric value, got {actual!r}"
        raise TypeError(message)
    if not math.isclose(float(actual), expected):
        message = f"{description}: expected {expected!r}, got {actual!r}"
        raise AssertionError(message)


def require_array(value: JsonValue, description: str) -> list[JsonValue]:
    """Require a JSON array in decoded test output.

    Returns:
        Narrowed JSON array.

    Raises:
        TypeError: If the value is not an array.
    """
    if isinstance(value, list):
        return value
    message = f"{description}: expected JSON array, got {type(value).__name__}"
    raise TypeError(message)


@dataclass(frozen=True)
class AccountOverrides:
    """Optional values for one parsed-account fixture."""

    auth_valid: bool | None = True
    status: str = "available"
    used: float | None = 25.0
    remaining: float | None = 75.0
    redeemable_count: int | None = 2
    stale: bool = False
    probe_error: str | None = None


class UsageTimeSeriesCase(unittest.TestCase):
    """Provide an isolated filesystem root for each persistence test."""

    root: Path

    def setUp(self) -> None:
        """Create an isolated filesystem-backed store root."""
        self.root = self.enterContext(isolated_root())

    def store(self, *, legacy: Path | None = None) -> UsageTimeSeriesStore:
        """Create a durable store inside the isolated root.

        Returns:
            Initialized test store.
        """
        return UsageTimeSeriesStore(
            self.root / "private" / "usage-history.sqlite3",
            sample_interval_seconds=SAMPLE_INTERVAL_SECONDS,
            collector_version="test-sha",
            legacy_json_path=legacy,
        )


def raw_account(label: str, account_id: str) -> JsonObject:
    """Create redacted broker metadata for one account.

    Returns:
        Broker account object containing only metadata.
    """
    metadata: JsonObject = {"label": label, "account_id": account_id}
    return {"metadata": metadata}


def parsed_account(label: str, overrides: AccountOverrides | None = None) -> JsonObject:
    """Create one parsed dashboard account.

    Returns:
        Secret-free parsed account fixture.
    """
    values = overrides or AccountOverrides()
    reset_at = (NOW + timedelta(hours=3)).isoformat() if values.used is not None else None
    weekly_reset = (NOW + timedelta(days=5)).isoformat() if values.used is not None else None
    return {
        "label": label,
        "enabled": True,
        "auth_valid": values.auth_valid,
        "status": values.status,
        "availability": values.status,
        "five_hour": {
            "used_percent": values.used,
            "remaining_percent": values.remaining,
            "reset_at": reset_at,
            "window_seconds": 18_000 if values.used is not None else None,
        },
        "weekly": {
            "used_percent": 10.0 if values.used is not None else None,
            "remaining_percent": 90.0 if values.used is not None else None,
            "reset_at": weekly_reset,
            "window_seconds": 604_800 if values.used is not None else None,
        },
        "reset_credits": {
            "available_count": values.redeemable_count,
            "updated_at": NOW.isoformat(),
            "stale": values.stale,
            "probe_error": values.probe_error,
        },
        "token_usage": {
            "daily": [{"date": NOW.date().isoformat(), "tokens": 400}],
            "updated_at": NOW.isoformat(),
            "stale": values.stale,
            "probe_error": values.probe_error,
        },
        "last_probe_at": NOW.isoformat(),
        "stale": values.stale,
        "stale_seconds": 30,
        "probe_error": values.probe_error,
    }


def legacy_payload() -> JsonObject:
    """Create one legacy JSON-ledger batch.

    Returns:
        Version-one legacy ledger fixture.
    """
    return {
        "schema_version": 1,
        "samples": [
            {
                "at": (NOW - timedelta(minutes=5)).isoformat(),
                "accounts": {
                    "Seth": {
                        "enabled": True,
                        "auth_valid": True,
                        "status": "available",
                        "five_used_percent": 20,
                        "five_reset_at": (NOW + timedelta(hours=3)).isoformat(),
                        "weekly_used_percent": 10,
                        "weekly_reset_at": (NOW + timedelta(days=5)).isoformat(),
                        "token_date": NOW.date().isoformat(),
                        "tokens_today": 300,
                    },
                },
            },
        ],
    }
