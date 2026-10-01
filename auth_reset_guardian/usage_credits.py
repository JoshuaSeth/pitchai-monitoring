# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provider-confirmed credit capacity, separate from included quota and resets."""

import re
from decimal import Decimal
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
        text = str(raw).strip()
        if re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,9})?", text):
            value = Decimal(text)
            if value >= 0:
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
    elif (
        limits.get("allowed") is not True or limits.get("limit_reached") is not False
    ) and not _models_available(payload):
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


def _models_available(payload: dict[str, JsonValue]) -> bool:
    """Require explicit permission from every reported model before using credits.

    Returns:
        Whether the nonempty model map consistently confirms availability.
    """
    models = _mapping(payload.get("model_usage"))
    if not models:
        return False
    for raw_model in models.values():
        model = _mapping(raw_model)
        if model.get("available") is not True or model.get("credits_would_enable") is not False:
            return False
    return True
