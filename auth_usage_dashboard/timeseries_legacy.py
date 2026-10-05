# Copyright (c) 2026 PitchAI. All rights reserved.
"""One-time import of the former redacted JSON sample ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from .timeseries_rows import fallback_account_ref
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    text_value,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from .timeseries_types import JsonObject, JsonValue, SqlRow

LEGACY_SOURCE = "auth_usage_dashboard:legacy_json_v1"
type LegacyBatch = tuple[str, list[SqlRow]]


def load_legacy_batches(
    path: Path,
    *,
    references: Mapping[str, str],
    collector_version: str,
) -> list[LegacyBatch]:
    """Load and validate legacy samples without exposing non-redacted state.

    Returns:
        Validated legacy batches ready for transactional import.

    Raises:
        TypeError: If the legacy document shape is malformed.
        ValueError: If its schema or timestamps are invalid.
    """
    decoded = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
        message = "unsupported legacy usage sample schema"
        raise ValueError(message)
    raw_samples = decoded.get("samples")
    if not isinstance(raw_samples, list):
        message = "legacy usage sample store is malformed"
        raise TypeError(message)
    batches: list[LegacyBatch] = []
    for raw_sample in raw_samples:
        if not isinstance(raw_sample, dict):
            message = "legacy usage sample is malformed"
            raise TypeError(message)
        sampled_at = _timestamp(raw_sample.get("at"))
        accounts = raw_sample.get("accounts")
        if not isinstance(accounts, dict):
            message = "legacy usage sample accounts are malformed"
            raise TypeError(message)
        rows = _account_rows(
            accounts,
            sampled_at=sampled_at,
            references=references,
            collector_version=collector_version,
        )
        batches.append((sampled_at, rows))
    return batches


def _account_rows(
    accounts: JsonObject,
    *,
    sampled_at: str,
    references: Mapping[str, str],
    collector_version: str,
) -> list[SqlRow]:
    rows: list[SqlRow] = []
    for raw_label, raw_account in accounts.items():
        if not isinstance(raw_account, dict):
            message = "legacy usage sample account is malformed"
            raise TypeError(message)
        account_ref = references.get(raw_label, fallback_account_ref(raw_label))
        rows.append(
            _legacy_row(
                raw_account,
                label=raw_label,
                account_ref=account_ref,
                sampled_at=sampled_at,
                collector_version=collector_version,
            ),
        )
    return rows


def _legacy_row(
    account: JsonObject,
    *,
    label: str,
    account_ref: str,
    sampled_at: str,
    collector_version: str,
) -> SqlRow:
    five_used = number_value(account.get("five_used_percent"))
    weekly_used = number_value(account.get("weekly_used_percent"))
    auth_valid = account.get("auth_valid") is True
    status = text_value(account.get("status")) or "unknown"
    auth_state = "valid" if auth_valid else "invalid" if status == "auth_invalid" else "unknown"
    return {
        "sampled_at": sampled_at,
        "account_label": label,
        "account_ref": account_ref,
        "enabled": 1 if account.get("enabled") is True else 0,
        "auth_state": auth_state,
        "account_status": status,
        "availability": status,
        "five_used_percent": five_used,
        "five_remaining_percent": _remaining(five_used),
        "five_reset_at": text_value(account.get("five_reset_at")),
        "five_window_seconds": None,
        "weekly_used_percent": weekly_used,
        "weekly_remaining_percent": _remaining(weekly_used),
        "weekly_reset_at": text_value(account.get("weekly_reset_at")),
        "weekly_window_seconds": None,
        "redeemable_count": None,
        "provider_observed_at": None,
        "provider_age_seconds": None,
        "provider_stale": 1,
        "reset_inventory_observed_at": None,
        "reset_inventory_stale": None,
        "token_usage_observed_at": None,
        "token_usage_stale": None,
        "probe_error": None,
        "reset_inventory_error": None,
        "token_usage_error": None,
        "values_source": "legacy",
        "carried_fields_json": "[]",
        "token_date": text_value(account.get("token_date")),
        "tokens_today": nonnegative_integer(account.get("tokens_today")),
        "source": LEGACY_SOURCE,
        "collector_version": collector_version,
    }


def _timestamp(value: JsonValue) -> str:
    if not isinstance(value, str) or not value.strip():
        message = "legacy usage sample timestamp is missing"
        raise ValueError(message)
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        message = "legacy usage sample timestamp lacks a timezone"
        raise ValueError(message)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _remaining(used: float | None) -> float | None:
    return None if used is None else round(max(0.0, 100.0 - used), 2)
