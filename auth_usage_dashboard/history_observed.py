# Copyright (c) 2026 PitchAI. All rights reserved.
"""Observed provider-token deltas between consecutive usage samples."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from .history_values import floor_hour, parse_datetime, sample_accounts, sample_integer

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject

_MINIMUM_PAIR_SAMPLES = 2


def observed_token_deltas(
    samples: list[JsonObject],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, dict[datetime, int]]:
    """Sum same-day token-counter increases per account label and UTC hour.

    Returns:
        Observed token deltas keyed by account label, then by hour start.
    """
    observed: dict[str, dict[datetime, int]] = {}
    if len(samples) < _MINIMUM_PAIR_SAMPLES:
        return observed
    ordered = sorted(samples, key=_sample_order)
    for previous, current in pairwise(ordered):
        current_at = parse_datetime(current.get("at"))
        if current_at is None or current_at < start or current_at > end:
            continue
        hour = floor_hour(current_at)
        for label, delta in _token_deltas(previous, current).items():
            label_hours = observed.setdefault(label, {})
            label_hours[hour] = label_hours.get(hour, 0) + delta
    return observed


def _sample_order(sample: JsonObject) -> str:
    captured_at = sample.get("at", "")
    if isinstance(captured_at, str):
        return captured_at
    message = "usage sample timestamps must be text"
    raise TypeError(message)


def _token_deltas(previous: JsonObject, current: JsonObject) -> dict[str, int]:
    deltas: dict[str, int] = {}
    current_accounts = sample_accounts(current)
    if not current_accounts:
        return deltas
    previous_accounts = sample_accounts(previous)
    for label, current_account in current_accounts.items():
        previous_account = previous_accounts.get(label)
        if not isinstance(previous_account, dict) or not isinstance(current_account, dict):
            continue
        delta = _token_delta(previous_account, current_account)
        if delta is not None:
            deltas[label] = delta
    return deltas


def _token_delta(previous_account: JsonObject, current_account: JsonObject) -> int | None:
    if previous_account.get("token_date") != current_account.get("token_date"):
        return None
    previous_total = sample_integer(previous_account.get("tokens_today"))
    current_total = sample_integer(current_account.get("tokens_today"))
    if previous_total is None or current_total is None or current_total <= previous_total:
        return None
    return current_total - previous_total
