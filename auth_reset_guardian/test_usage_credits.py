# Copyright (c) 2026 PitchAI. All rights reserved.
"""Credit parsing preserves exact balances and rejects malformed permission."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .test_organization_assertions import require_equal
from .usage_credits import usage_credits

if TYPE_CHECKING:
    from .usage_credits import JsonValue


def test_finite_credit_balance_and_permission() -> None:
    """Only valid existing credit and explicit provider permission are usable."""
    cases: tuple[tuple[JsonValue, bool], ...] = (
        ("24956.4051470000", True), ("1e3", True), (".5", True),
        (0, False), ("-1", False), (True, False), ("NaN", False),
        ("Infinity", False), ("invalid", False), ("1e999999999999999999999", False),
    )
    for balance, expected in cases:
        payload: JsonValue = {
            "credits": {
                "balance": balance, "has_credits": True,
                "unlimited": False, "overage_limit_reached": False,
            },
            "rate_limit": {"allowed": True, "limit_reached": False},
            "spend_control": {"reached": False},
        }
        require_equal(usage_credits(payload)["usable"], expected)
    exact = usage_credits({"credits": {"balance": "24956.4051470000"}})
    require_equal(exact["balance"], "24956.4051470000")
    require_equal(exact["usable"], expected=False)


def test_model_permission_preserves_existing_credit_admission() -> None:
    """Model permission can establish usable credits after included quota denial."""
    permitted: JsonValue = {"available": True, "credits_would_enable": False}
    cases: tuple[tuple[JsonValue, bool], ...] = (
        ({"astra": permitted}, True),
        ({"astra": permitted, "other": permitted}, True),
        ({}, False), (None, False), ([], False),
        ({"astra": {"available": True}}, False),
        ({"astra": {"available": True, "credits_would_enable": True}}, False),
        ({"astra": {"available": 1, "credits_would_enable": False}}, False),
        ({"astra": permitted, "other": None}, False),
    )
    for models, expected in cases:
        for balance, spending_allowed in (("10", True), ("0", True), ("10", False)):
            payload: JsonValue = {
                "credits": {
                    "balance": balance, "has_credits": True,
                    "unlimited": False, "overage_limit_reached": False,
                },
                "rate_limit": {"allowed": False, "limit_reached": True},
                "spend_control": {"reached": not spending_allowed},
                "model_usage": models,
            }
            usable = usage_credits(payload)["usable"]
            require_equal(usable, expected and balance != "0" and spending_allowed)
