# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed per-account deltas for aggregate scheduling burn windows."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .history import isoformat, parse_datetime
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    optional_object,
    text_value,
)

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

type AccountDelta = tuple[float | None, int | None]
type SampleWindow = tuple[float, str]
type SampleTimes = tuple[datetime, datetime]


def eligible_account(account: JsonObject) -> bool:
    """Return whether the broker says an account contributes burnable capacity."""
    return (
        account.get("enabled") is True
        and account.get("auth_valid") is True
        and account.get("stale") is not True
    )


def eligible_labels(accounts: list[JsonObject]) -> set[str]:
    """Return redacted sample keys for broker-burnable accounts."""
    labels: set[str] = set()
    for account in accounts:
        label = text_value(account.get("label"))
        if label is not None and eligible_account(account):
            labels.add(label)
    return labels


def account_deltas(
    previous_accounts: JsonObject,
    current_accounts: JsonObject,
    *,
    labels: set[str],
    sample_times: SampleTimes,
    window_key: str,
) -> dict[str, AccountDelta]:
    """Return valid capacity and token deltas keyed by eligible account label."""
    deltas: dict[str, AccountDelta] = {}
    for label in labels:
        previous = optional_object(previous_accounts.get(label))
        current = optional_object(current_accounts.get(label))
        if previous and current:
            deltas[label] = _account_delta(
                previous,
                current,
                sample_times=sample_times,
                window_key=window_key,
            )
    return deltas


def _account_delta(
    previous: JsonObject,
    current: JsonObject,
    *,
    sample_times: SampleTimes,
    window_key: str,
) -> AccountDelta:
    return (
        _capacity_delta(
            previous,
            current,
            sample_times=sample_times,
            window_key=window_key,
        ),
        _provider_token_delta(previous, current),
    )


def _capacity_delta(
    previous: JsonObject,
    current: JsonObject,
    *,
    sample_times: SampleTimes,
    window_key: str,
) -> float | None:
    previous_at, current_at = sample_times
    previous_window = _sample_window(previous, at=previous_at, key=window_key)
    current_window = _sample_window(current, at=current_at, key=window_key)
    if previous_window is None or current_window is None:
        return None
    previous_used, previous_reset = previous_window
    current_used, current_reset = current_window
    if previous_reset == current_reset and current_used >= previous_used:
        return current_used - previous_used
    return None


def _provider_token_delta(
    previous: JsonObject,
    current: JsonObject,
) -> int | None:
    previous_tokens = nonnegative_integer(previous.get("tokens_today"))
    current_tokens = nonnegative_integer(current.get("tokens_today"))
    if (
        previous.get("token_date") == current.get("token_date")
        and previous_tokens is not None
        and current_tokens is not None
        and current_tokens >= previous_tokens
    ):
        return current_tokens - previous_tokens
    return None


def _sample_window(
    account: JsonObject,
    *,
    at: datetime,
    key: str,
) -> SampleWindow | None:
    prefix = "five" if key == "five_hour" else "weekly"
    used = number_value(account.get(f"{prefix}_used_percent"))
    reset_at = parse_datetime(text_value(account.get(f"{prefix}_reset_at")))
    if used is not None and reset_at is not None:
        return used, isoformat(reset_at)
    if key != "weekly":
        return None
    legacy_used = number_value(account.get("five_used_percent"))
    legacy_reset = parse_datetime(text_value(account.get("five_reset_at")))
    if legacy_used is not None and legacy_reset is not None:
        if legacy_reset - at > timedelta(hours=6):
            return legacy_used, isoformat(legacy_reset)
    return None
