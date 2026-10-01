# Copyright (c) 2026 PitchAI. All rights reserved.
"""Project provider spending capacity without confusing it with banked resets."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, TypedDict, cast

FundingState = Literal["unreported", "none", "possible", "unknown"]


class FundedUsageDocument(TypedDict, total=False):
    """Unvalidated optional fields at the provider usage JSON boundary."""

    credits: object
    model_usage: object
    spend_control: object


class FundedCapacity(TypedDict):
    """Secret-free classifications retained from the same fresh usage response."""

    credits: FundingState
    models: FundingState
    spend_control: FundingState


class FundedCapacityDocument(TypedDict):
    """Optional sanitized observation field from live or historical sources."""

    funded_capacity: object


class CreditAmount(TypedDict):
    """Unvalidated provider balance or spend-limit amount."""

    value: object


def sanitize_funded_capacity(payload: FundedUsageDocument) -> FundedCapacity:
    """Classify only reported spending fields, preserving legacy absence.

    Returns:
        Positive or uncertain evidence that requires actual execution proof.
    """
    credit_state: FundingState = "unreported"
    if "credits" in payload:
        credit_state = _credit_state(payload)
    models: FundingState = "unreported"
    raw_models = payload.get("model_usage")
    if raw_models is not None:
        models = _model_state(payload)
    spend: FundingState = "unreported"
    raw_spend = payload.get("spend_control")
    if raw_spend is not None:
        spend = "unknown"
        if isinstance(raw_spend, dict):
            control = cast("dict[str, object]", raw_spend)
            reached = control.get("reached")
            limit = control.get("individual_limit")
            if isinstance(reached, bool) and (limit is None or _balance_is_valid(CreditAmount(value=limit))):
                spend = "none"
    return FundedCapacity(credits=credit_state, models=models, spend_control=spend)


def _balance_is_valid(amount: CreditAmount) -> bool:
    value = amount["value"]
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return False
    return re.fullmatch(r"\+?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", str(value)) is not None


def _credit_state(payload: FundedUsageDocument) -> FundingState:
    raw = payload.get("credits")
    if not isinstance(raw, dict):
        return "unknown"
    credit_fields = cast("dict[str, object]", raw)
    has_credits = credit_fields.get("has_credits")
    unlimited = credit_fields.get("unlimited")
    balance = credit_fields.get("balance")
    overage = credit_fields.get("overage_limit_reached")
    if not isinstance(has_credits, bool) or not isinstance(unlimited, bool):
        return "unknown"
    if overage is not None and not isinstance(overage, bool):
        return "unknown"
    if unlimited or has_credits:
        return "possible"
    if not _balance_is_valid(CreditAmount(value=balance)):
        return "unknown"
    return "possible" if Decimal(str(balance)) > 0 else "none"


def _model_state(payload: FundedUsageDocument) -> FundingState:
    raw = payload.get("model_usage")
    if not isinstance(raw, dict):
        return "unknown"
    models = cast("dict[str, object]", raw)
    result: FundingState = "unreported"
    for raw_model in models.values():
        if not isinstance(raw_model, dict):
            return "unknown"
        model = cast("dict[str, object]", raw_model)
        available = model.get("available")
        credits_enable = model.get("credits_would_enable")
        if not isinstance(available, bool) or not isinstance(credits_enable, bool):
            return "unknown"
        if available or credits_enable:
            result = "possible"
        elif result != "possible":
            result = "none"
    return result


def funding_requires_execution_proof(document: FundedCapacityDocument) -> bool:
    """Reject uncertain sanitized evidence without treating legacy absence as fatal.

    Returns:
        Whether quota-only denial is insufficient for effective exhaustion.
    """
    raw = document["funded_capacity"]
    if raw is None:
        return False
    if not isinstance(raw, dict):
        return True
    capacity = cast("dict[str, object]", raw)
    return any(
        not isinstance(capacity.get(key), str) or capacity[key] not in {"none", "unreported"}
        for key in ("credits", "models", "spend_control")
    )
