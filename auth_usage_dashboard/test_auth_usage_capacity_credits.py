# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof that purchased usage credits extend capacity without hiding included usage."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ._broker_account_test_fixtures import NOW, add_usage_credits, member, parse_raw, raw_account
from ._timeseries_test_fixtures import check, check_equal

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

FUNDED_BALANCE = "62500"
EMPTY_BALANCE = "0"


def _parsed_with_usage_credits(blocked: str | None) -> JsonObject:
    """Parse an exhausted account holding usage credits and one optional blocker.

    Returns:
        The parsed account, after proving included usage and banked resets are unchanged.
    """
    raw = raw_account(
        "credits@example.com",
        five_used=100,
        weekly_used=100,
        enabled=blocked != "disabled",
    )
    rate_limit = member(raw, "state", "usage", "rate_limit")
    rate_limit.update({"allowed": blocked != "provider", "limit_reached": blocked == "provider"})
    balance = EMPTY_BALANCE if blocked == "empty" else FUNDED_BALANCE
    add_usage_credits(
        raw,
        balance=balance,
        overage_reached=blocked == "overage",
        spending_reached=blocked == "spending",
    )
    if blocked == "stale":
        member(raw, "state")["last_probe_at"] = (NOW - timedelta(hours=1)).isoformat()

    parsed = parse_raw(raw)

    check_equal(member(parsed, "weekly")["remaining_percent"], 0, "included weekly usage stays exhausted")
    check_equal(member(parsed, "usage_credits")["balance"], balance, "usage credit balance")
    check_equal(member(parsed, "reset_credits")["available_count"], 2, "banked reset credits")
    return parsed


def test_funded_usage_credits_make_exhausted_account_selectable() -> None:
    """Prove funded usage credits keep an exhausted account selectable."""
    parsed = _parsed_with_usage_credits(None)
    check(parsed["selectable_now"] is True, "funded usage credits extend capacity")


def test_empty_usage_credit_balance_does_not_extend_capacity() -> None:
    """Prove an empty usage-credit balance does not extend capacity."""
    parsed = _parsed_with_usage_credits("empty")
    check(parsed["selectable_now"] is False, "an empty balance does not extend capacity")


def test_reached_overage_limit_blocks_usage_credits() -> None:
    """Prove a reached overage limit blocks usage credits."""
    parsed = _parsed_with_usage_credits("overage")
    check(parsed["selectable_now"] is False, "a reached overage limit blocks usage credits")


def test_reached_spend_control_blocks_usage_credits() -> None:
    """Prove a reached spend control blocks usage credits."""
    parsed = _parsed_with_usage_credits("spending")
    check(parsed["selectable_now"] is False, "a reached spend control blocks usage credits")


def test_provider_rate_limit_blocks_usage_credits() -> None:
    """Prove a provider-reached rate limit blocks usage credits."""
    parsed = _parsed_with_usage_credits("provider")
    check(parsed["selectable_now"] is False, "a provider rate limit blocks usage credits")


def test_stale_probe_blocks_usage_credits() -> None:
    """Prove a stale broker probe blocks usage credits."""
    parsed = _parsed_with_usage_credits("stale")
    check(parsed["selectable_now"] is False, "a stale probe blocks usage credits")


def test_disabled_account_blocks_usage_credits() -> None:
    """Prove a disabled account is not selectable through usage credits."""
    parsed = _parsed_with_usage_credits("disabled")
    check(parsed["selectable_now"] is False, "a disabled account is not selectable")
