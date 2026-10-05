# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provider-confirmed credit capacity, separate from included quota and resets."""

from __future__ import annotations

from contextlib import suppress
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, TypedDict

from .timeseries_types import JsonValue, optional_object

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

__all__ = ["JsonValue", "UsageCredits", "usage_credits"]

_CREDITS_AVAILABLE = "Credits available for continued usage"


class UsageCredits(TypedDict):
    """Redacted provider balance and permission to use it."""

    balance: str | None
    unlimited: bool
    usable: bool
    reason: str


def usage_credits(usage: JsonValue) -> UsageCredits:
    """Read spendable credits without inferring permission from a balance alone.

    The first failed confirmation, in precedence order, explains why credits
    are unusable; only a fully confirmed summary allows continued usage.

    Returns:
        A finite balance in provider credit units and explicit usability status.
    """
    summary = optional_object(usage)
    credit_fields = optional_object(summary.get("credits"))
    rate_limit = optional_object(summary.get("rate_limit"))
    spend_control = optional_object(summary.get("spend_control"))
    balance = _finite_balance(credit_fields.get("balance"))
    unlimited = credit_fields.get("unlimited") is True
    funded = unlimited or (balance is not None and Decimal(balance) > 0)
    provider_blocks = rate_limit.get("allowed") is not True or rate_limit.get("limit_reached") is not False
    blockers = (
        (not credit_fields, "Credit balance not reported"),
        (credit_fields.get("has_credits") is not True or not funded, "No confirmed credit capacity"),
        (credit_fields.get("overage_limit_reached") is not False, "Credit spending blocked or unconfirmed"),
        (spend_control.get("reached") is not False, "Spending permission blocked or unconfirmed"),
        (provider_blocks and not _every_model_available(summary), "Provider currently blocks requests"),
    )
    reason = next((message for blocked, message in blockers if blocked), _CREDITS_AVAILABLE)
    return {"balance": balance, "unlimited": unlimited, "usable": reason == _CREDITS_AVAILABLE, "reason": reason}


def _finite_balance(raw: JsonValue) -> str | None:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    value = Decimal("NaN")
    with suppress(InvalidOperation):
        value = Decimal(str(raw))
    if value.is_finite() and value >= 0:
        return str(value)
    return None


def _every_model_available(summary: JsonObject) -> bool:
    models = optional_object(summary.get("model_usage"))
    if not models:
        return False
    for model_value in models.values():
        model = optional_object(model_value)
        if model.get("available") is not True or model.get("credits_would_enable") is not False:
            return False
    return True
