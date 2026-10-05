# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build secret-free rows for the broker usage time-series database."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC
from typing import TYPE_CHECKING

from .timeseries_types import (
    nonnegative_integer,
    number_value,
    optional_flag,
    optional_object,
    text_value,
)

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject, JsonValue, SqlRow

SOURCE = "auth_usage_dashboard:redacted_broker_state"
_SAFE_ERROR_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,79}")
_LAST_KNOWN_FIELDS = (
    "five_used_percent",
    "five_remaining_percent",
    "five_reset_at",
    "five_window_seconds",
    "weekly_used_percent",
    "weekly_remaining_percent",
    "weekly_reset_at",
    "weekly_window_seconds",
    "redeemable_count",
    "token_date",
    "tokens_today",
)


def account_references(raw_accounts: list[JsonObject]) -> dict[str, str]:
    """Map labels to stable one-way broker account fingerprints.

    Returns:
        Account labels mapped to SHA-256 references.
    """
    references: dict[str, str] = {}
    for raw_account in raw_accounts:
        metadata = optional_object(raw_account.get("metadata"))
        label = text_value(metadata.get("label"))
        account_id = text_value(metadata.get("account_id"))
        if label is not None and account_id is not None:
            references[label] = f"sha256:{hashlib.sha256(account_id.encode()).hexdigest()}"
    return references


def sample_row(
    account: JsonObject,
    *,
    account_ref: str,
    sampled_at: datetime,
    collector_version: str,
) -> SqlRow:
    """Project one parsed dashboard account into the durable row contract.

    Returns:
        Secret-free row ready for insertion.
    """
    five_hour = optional_object(account.get("five_hour"))
    weekly = optional_object(account.get("weekly"))
    reset_credits = optional_object(account.get("reset_credits"))
    token_usage = optional_object(account.get("token_usage"))
    tokens_today = _today_tokens(token_usage, sampled_at)
    sampled_at_text = sampled_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    auth_valid = account.get("auth_valid")
    auth_state = "valid" if auth_valid is True else "invalid" if auth_valid is False else "unknown"
    row: SqlRow = {
        "sampled_at": sampled_at_text,
        "account_label": text_value(account.get("label")) or "Unlabeled account",
        "account_ref": account_ref,
        "enabled": 1 if account.get("enabled") is True else 0,
        "auth_state": auth_state,
        "account_status": text_value(account.get("status")) or "unknown",
        "availability": text_value(account.get("availability")) or "unknown",
        "five_used_percent": number_value(five_hour.get("used_percent")),
        "five_remaining_percent": number_value(five_hour.get("remaining_percent")),
        "five_reset_at": text_value(five_hour.get("reset_at")),
        "five_window_seconds": nonnegative_integer(five_hour.get("window_seconds")),
        "weekly_used_percent": number_value(weekly.get("used_percent")),
        "weekly_remaining_percent": number_value(weekly.get("remaining_percent")),
        "weekly_reset_at": text_value(weekly.get("reset_at")),
        "weekly_window_seconds": nonnegative_integer(weekly.get("window_seconds")),
        "redeemable_count": nonnegative_integer(reset_credits.get("available_count")),
        "provider_observed_at": text_value(account.get("last_probe_at")),
        "provider_age_seconds": nonnegative_integer(account.get("stale_seconds")),
        "provider_stale": 1 if account.get("stale") is True else 0,
        "reset_inventory_observed_at": text_value(reset_credits.get("updated_at")),
        "reset_inventory_stale": optional_flag(reset_credits.get("stale")),
        "token_usage_observed_at": text_value(token_usage.get("updated_at")),
        "token_usage_stale": optional_flag(token_usage.get("stale")),
        "probe_error": sanitized_error_code(account.get("probe_error")),
        "reset_inventory_error": sanitized_error_code(reset_credits.get("probe_error")),
        "token_usage_error": sanitized_error_code(token_usage.get("probe_error")),
        "values_source": "current" if _has_measurement(five_hour, weekly, reset_credits) else "unavailable",
        "carried_fields_json": "[]",
        "token_date": sampled_at.astimezone(UTC).date().isoformat() if tokens_today is not None else None,
        "tokens_today": tokens_today,
        "source": SOURCE,
        "collector_version": collector_version,
    }
    return row


def carry_last_known(row: SqlRow, previous: SqlRow | None) -> SqlRow:
    """Retain prior measurements for auth-invalid rows without calling them current.

    Returns:
        The row with eligible prior measurements marked as carried.
    """
    if row["auth_state"] != "invalid":
        return row
    carried: list[str] = []
    if previous is not None:
        for field in _LAST_KNOWN_FIELDS:
            if row[field] is None and previous.get(field) is not None:
                previous_value = previous[field]
                if isinstance(previous_value, (str, int, float)):
                    row[field] = previous_value
                    carried.append(field)
    if any(row[field] is not None for field in _LAST_KNOWN_FIELDS):
        row["values_source"] = "last_known"
    row["carried_fields_json"] = json.dumps(carried, separators=(",", ":"))
    return row


def fallback_account_ref(label: str) -> str:
    """Create a namespaced fallback only when broker metadata lacks an identifier.

    Returns:
        Stable one-way label-based fallback reference.
    """
    digest = hashlib.sha256(f"missing-account-id:{label}".encode()).hexdigest()
    return f"fallback-sha256:{digest}"


def sanitized_error_code(value: JsonValue) -> str | None:
    """Retain safe error codes and fingerprint every free-form error.

    Returns:
        A bounded code, a one-way error fingerprint, or None.
    """
    raw_error = text_value(value)
    if raw_error is None:
        return None
    if _SAFE_ERROR_CODE.fullmatch(raw_error) is not None:
        return raw_error
    digest = hashlib.sha256(raw_error.encode()).hexdigest()
    return f"error-sha256:{digest}"


def _has_measurement(*values: JsonObject) -> bool:
    fields = ("used_percent", "remaining_percent", "available_count")
    return any(value.get(field) is not None for value in values for field in fields)


def _today_tokens(
    token_usage: JsonObject,
    sampled_at: datetime,
) -> int | None:
    target = sampled_at.astimezone(UTC).date().isoformat()
    daily = token_usage.get("daily")
    if not isinstance(daily, list):
        return None
    for point in daily:
        if not isinstance(point, dict) or point.get("date") != target:
            continue
        return nonnegative_integer(point.get("tokens"))
    return None
