# Copyright (c) 2026 PitchAI. All rights reserved.
"""Aggregate redacted account reset credits into dashboard inventory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .value_parsing import optional_isoformat, parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityAccount, ResetBank, ResetBankDetail, ResetCreditDetail


def build_reset_bank(accounts: list[CapacityAccount], *, now: datetime) -> ResetBank:
    """Build aggregate counts and bounded reset-credit details.

    Returns:
        The resulting value.

    """
    details: list[ResetBankDetail] = []
    known_counts: list[int] = []
    count_only_accounts = 0
    for account in accounts:
        reset_state = account["reset_credits"]
        count = reset_state["available_count"]
        account_details = reset_state["details"]
        if count is not None:
            known_counts.append(count)
            if count > len(account_details):
                count_only_accounts += 1
        details.extend(_bank_detail(account["label"], detail, now=now) for detail in account_details)
    details.sort(key=_detail_sort_key)
    return {
        "total_available": sum(known_counts),
        "accounts_with_known_count": len(known_counts),
        "accounts_with_unknown_count": len(accounts) - len(known_counts),
        "count_only_accounts": count_only_accounts,
        "detail_count": len(details),
        "details": details,
        "earliest_expiry_at": optional_isoformat(
            _earliest_expiry(details, now=now),
        ),
        "stale_account_count": sum(1 for account in accounts if account["reset_credits"]["stale"]),
    }


def _bank_detail(
    account_label: str,
    detail: ResetCreditDetail,
    *,
    now: datetime,
) -> ResetBankDetail:
    expires_at = parse_datetime(detail.get("expires_at"))
    return {
        "account_label": account_label,
        "reset_type": detail.get("reset_type"),
        "status": detail.get("status"),
        "title": detail.get("title"),
        "granted_at": detail.get("granted_at"),
        "expires_at": detail.get("expires_at"),
        "expires_in_seconds": (None if expires_at is None else int((expires_at - now).total_seconds())),
    }


def _detail_sort_key(detail: ResetBankDetail) -> tuple[bool, str, str]:
    return (
        detail["expires_at"] is None,
        detail["expires_at"] or "",
        detail["account_label"].lower(),
    )


def _earliest_expiry(
    details: list[ResetBankDetail],
    *,
    now: datetime,
) -> datetime | None:
    future: list[datetime] = []
    for detail in details:
        expiry = parse_datetime(detail.get("expires_at"))
        if expiry is not None and expiry > now:
            future.append(expiry)
    return min(future, default=None)
