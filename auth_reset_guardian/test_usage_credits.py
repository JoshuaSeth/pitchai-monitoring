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
