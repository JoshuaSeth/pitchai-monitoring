# Copyright (c) 2026 PitchAI. All rights reserved.
"""Operator warnings about broker freshness, account health, and pool depth."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .timeseries_types import optional_object

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_UNRANKED_SEVERITY = 9
_NEAR_ZERO_REMAINING_PERCENT = 20
_LOW_POOL_ACCOUNTS = 1


def build_warnings(
    accounts: list[JsonObject],
    *,
    source_error: str | None,
    history_error: str | None,
    probe_errors: dict[str, str],
    analytics_probe_errors: dict[str, str],
) -> list[JsonValue]:
    """Collect fleet and per-account warnings, most severe first.

    Returns:
        Warnings ordered by severity and then account label.
    """
    warnings: list[JsonObject] = []
    if source_error:
        warnings.append(_warning("critical", "source_error", "Broker state refresh failed"))
    if history_error:
        warnings.append(_warning("warning", "history_error", "Usage sample history could not be persisted"))
    if probe_errors:
        message = f"Freshness probe failed for {len(probe_errors)} account(s)"
        warnings.append(_warning("warning", "probe_error", message))
    if analytics_probe_errors:
        message = f"Token history or reset-bank refresh failed for {len(analytics_probe_errors)} account(s)"
        warnings.append(_warning("warning", "analytics_probe_error", message))
    warnings.extend(_coverage_warnings(accounts))
    for account in accounts:
        warnings.extend(_account_warnings(account))
    fresh_selectable = sum(1 for account in accounts if account["selectable_now"] and not account["stale"])
    if fresh_selectable <= _LOW_POOL_ACCOUNTS:
        warnings.append(_warning("critical", "low_pool", "One or fewer fresh accounts are selectable now"))
    warnings.sort(
        key=lambda item: (
            _SEVERITY_RANK.get(str(item["severity"]), _UNRANKED_SEVERITY),
            str(item.get("account_label", "")),
        ),
    )
    return [*warnings]


def _coverage_warnings(accounts: list[JsonObject]) -> list[JsonObject]:
    analytics_stale = 0
    five_hour_unreported = 0
    for account in accounts:
        if not account["enabled"]:
            continue
        if optional_object(account["token_usage"])["stale"] or optional_object(account["reset_credits"])["stale"]:
            analytics_stale += 1
        five_hour_reported = optional_object(account["five_hour"]).get("reported") is True
        if account["auth_valid"] is True and not account["stale"] and not five_hour_reported:
            five_hour_unreported += 1
    warnings: list[JsonObject] = []
    if analytics_stale:
        message = f"Usage history or reset-bank data is stale for {analytics_stale} account(s)"
        warnings.append(_warning("warning", "analytics_stale", message))
    if five_hour_unreported:
        message = f"Provider did not report a five-hour window for {five_hour_unreported} auth-valid account(s)"
        warnings.append(_warning("info", "five_hour_unreported", message))
    return warnings


def _account_warnings(account: JsonObject) -> list[JsonObject]:
    label = str(account["label"])
    status = account["status"]
    warnings: list[JsonObject] = []
    if status == "auth_invalid":
        message = "Account needs login or token refresh"
        warnings.append(_warning("critical", "auth_invalid", message, account_label=label))
    elif status == "unknown":
        warnings.append(_warning("warning", "unknown", account["status_reason"], account_label=label))
    if account["stale"] and account["enabled"]:
        warnings.append(_warning("warning", "stale", "Account usage state is stale", account_label=label))
    five_remaining = optional_object(account["five_hour"]).get("remaining_percent")
    if (
        status == "available"
        and isinstance(five_remaining, (int, float))
        and five_remaining <= _NEAR_ZERO_REMAINING_PERCENT
    ):
        message = f"Only {five_remaining:g}% of the five-hour window remains"
        warnings.append(_warning("warning", "near_zero", message, account_label=label))
    return warnings


def _warning(severity: str, code: str, message: JsonValue, *, account_label: str | None = None) -> JsonObject:
    if account_label is None:
        return {"severity": severity, "code": code, "message": message}
    return {"severity": severity, "code": code, "account_label": account_label, "message": message}
