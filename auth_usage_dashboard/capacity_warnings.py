# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build operator-facing warnings from normalized dashboard state."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CapacityAccount, DashboardWarning

_NEAR_ZERO_REMAINING_PERCENT = 20


def build_warnings(
    accounts: list[CapacityAccount],
    *,
    source_error: str | None,
    history_error: str | None,
    probe_errors: dict[str, str],
    analytics_probe_errors: dict[str, str],
) -> list[DashboardWarning]:
    """Build and severity-sort dashboard warnings.

    Returns:
        The resulting collection.

    """
    warnings = _boundary_warnings(
        source_error=source_error,
        history_error=history_error,
        probe_errors=probe_errors,
        analytics_probe_errors=analytics_probe_errors,
    )
    warnings.extend(_coverage_warnings(accounts))
    for account in accounts:
        warnings.extend(_account_warnings(account))
    selectable_accounts = (
        account for account in accounts if account["selectable_now"]
    )
    fresh_selectable_accounts = (
        account for account in selectable_accounts if not account["stale"]
    )
    fresh_selectable_count = sum(1 for _account in fresh_selectable_accounts)
    if fresh_selectable_count <= 1:
        warnings.append(
            {
                "severity": "critical",
                "code": "low_pool",
                "message": "One or fewer fresh accounts are selectable now",
            },
        )
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    warnings.sort(
        key=lambda item: (
            severity_rank.get(item["severity"], 9),
            item.get("account_label", ""),
        ),
    )
    return warnings


def _boundary_warnings(
    *,
    source_error: str | None,
    history_error: str | None,
    probe_errors: dict[str, str],
    analytics_probe_errors: dict[str, str],
) -> list[DashboardWarning]:
    warnings: list[DashboardWarning] = []
    if source_error:
        warnings.append(
            {
                "severity": "critical",
                "code": "source_error",
                "message": "Broker state refresh failed",
            },
        )
    if history_error:
        warnings.append(
            {
                "severity": "warning",
                "code": "history_error",
                "message": "Usage sample history could not be persisted",
            },
        )
    if probe_errors:
        warnings.append(
            {
                "severity": "warning",
                "code": "probe_error",
                "message": f"Freshness probe failed for {len(probe_errors)} account(s)",
            },
        )
    if analytics_probe_errors:
        warnings.append(
            {
                "severity": "warning",
                "code": "analytics_probe_error",
                "message": (f"Token history or reset-bank refresh failed for {len(analytics_probe_errors)} account(s)"),
            },
        )
    return warnings


def _coverage_warnings(accounts: list[CapacityAccount]) -> list[DashboardWarning]:
    warnings: list[DashboardWarning] = []
    analytics_stale_count = sum(
        1
        for account in accounts
        if account["enabled"] and (account["token_usage"]["stale"] or account["reset_credits"]["stale"])
    )
    if analytics_stale_count:
        warnings.append(
            {
                "severity": "warning",
                "code": "analytics_stale",
                "message": (f"Usage history or reset-bank data is stale for {analytics_stale_count} account(s)"),
            },
        )
    unreported = _unreported_five_hour_count(accounts)
    if unreported:
        warnings.append(
            {
                "severity": "info",
                "code": "five_hour_unreported",
                "message": (f"Provider did not report a five-hour window for {unreported} auth-valid account(s)"),
            },
        )
    return warnings


def _unreported_five_hour_count(accounts: list[CapacityAccount]) -> int:
    return sum(
        1
        for account in accounts
        if account["enabled"]
        and account["auth_valid"] is True
        and not account["stale"]
        and account["five_hour"].get("reported") is not True
    )


def _account_warnings(account: CapacityAccount) -> list[DashboardWarning]:
    warnings: list[DashboardWarning] = []
    status = account["status"]
    if status == "auth_invalid":
        warnings.append(
            _account_warning(
                account,
                severity="critical",
                code="auth_invalid",
                message="Account needs login or token refresh",
            ),
        )
    elif status == "unknown":
        warnings.append(
            _account_warning(
                account,
                severity="warning",
                code="unknown",
                message=account["status_reason"],
            ),
        )
    if account["stale"] and account["enabled"]:
        warnings.append(
            _account_warning(
                account,
                severity="warning",
                code="stale",
                message="Account usage state is stale",
            ),
        )
    five_remaining = account["five_hour"]["remaining_percent"]
    if status == "available" and five_remaining is not None and five_remaining <= _NEAR_ZERO_REMAINING_PERCENT:
        warnings.append(
            _account_warning(
                account,
                severity="warning",
                code="near_zero",
                message=f"Only {five_remaining:g}% of the five-hour window remains",
            ),
        )
    return warnings


def _account_warning(
    account: CapacityAccount,
    *,
    severity: str,
    code: str,
    message: str,
) -> DashboardWarning:
    return {
        "severity": severity,
        "code": code,
        "account_label": account["label"],
        "message": message,
    }
