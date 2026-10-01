# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provider-confirmed credit capacity, separate from included quota and resets."""

from decimal import Decimal, InvalidOperation
from typing import TypedDict, cast

JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None


class UsageCredits(TypedDict):
    """Redacted provider balance and permission to use it."""

    balance: str | None
    unlimited: bool
    usable: bool
    reason: str


def usage_credits(usage: JsonValue) -> UsageCredits:
    """Read spendable credits without inferring permission from a balance alone.

    Returns:
        A finite balance in provider credit units and explicit usability status.
    """
    payload = _mapping(usage)
    credit_fields = _mapping(payload.get("credits"))
    limits = _mapping(payload.get("rate_limit"))
    spending = _mapping(payload.get("spend_control"))
    raw = credit_fields.get("balance")
    balance = None
    if isinstance(raw, (str, int, float)) and not isinstance(raw, bool):
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            value = Decimal("NaN")
        if value.is_finite() and value >= 0:
            balance = str(value)
    unlimited = credit_fields.get("unlimited") is True
    funded = unlimited or (balance is not None and Decimal(balance) > 0)
    if not credit_fields:
        reason = "Credit balance not reported"
    elif credit_fields.get("has_credits") is not True or not funded:
        reason = "No confirmed credit capacity"
    elif credit_fields.get("overage_limit_reached") is not False:
        reason = "Credit spending blocked or unconfirmed"
    elif spending.get("reached") is not False:
        reason = "Spending permission blocked or unconfirmed"
    elif limits.get("allowed") is not True or limits.get("limit_reached") is not False:
        reason = "Provider currently blocks requests"
    else:
        reason = "Credits available for continued usage"
    return {
        "balance": balance,
        "unlimited": unlimited,
        "usable": reason == "Credits available for continued usage",
        "reason": reason,
    }


def _mapping(value: JsonValue) -> dict[str, JsonValue]:
    return cast("dict[str, JsonValue]", value) if isinstance(value, dict) else {}
