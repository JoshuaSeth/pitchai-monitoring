# Copyright (c) 2026 PitchAI. All rights reserved.
"""Mutate and validate deterministic simulation credit inventories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import PayloadError

if TYPE_CHECKING:
    from .json_contract import JsonObject, JsonValue


def next_simulation_outcome(
    account: JsonObject,
    provider_id: str,
) -> JsonValue:
    """Pop the next declared consume outcome for one provider credit.

    Returns:
        The declared outcome or the default non-terminal result.

    """
    outcomes = account.get("consume_outcomes")
    raw_outcome: JsonValue = None
    if isinstance(outcomes, dict):
        raw_outcome = outcomes.get(provider_id)
        if isinstance(raw_outcome, list):
            raw_outcome = raw_outcome.pop(0) if raw_outcome else None
    if raw_outcome is None:
        return {"code": "nothing_to_reset", "windows_reset": 0}
    return raw_outcome


def remove_simulation_credit(
    inventory: JsonObject,
    provider_id: str,
    *,
    count_available_only: bool,
) -> None:
    """Remove one credit and update the simulated inventory count."""
    reset_credits = required_simulation_object_list(
        inventory,
        "credits",
        context="simulation credit inventory",
    )
    remaining = [item for item in reset_credits if item.get("id") != provider_id]
    serialized_remaining: list[JsonValue] = []
    serialized_remaining.extend(remaining)
    inventory["credits"] = serialized_remaining
    if count_available_only:
        inventory["available_count"] = _available_inventory_count(remaining)
    else:
        inventory["available_count"] = len(remaining)


def _available_inventory_count(inventory_credits: list[JsonObject]) -> int:
    """Count credits whose provider status is available.

    Returns:
        The computed value.

    """
    available_count = 0
    for credit in inventory_credits:
        if credit.get("status") == "available":
            available_count += 1
    return available_count


def required_simulation_object(
    container: JsonObject,
    key: str,
    *,
    context: str,
) -> JsonObject:
    """Return one required nested object from a simulation fixture.

    Raises:
        PayloadError: If provider data violates the payload contract.

    """
    value = container.get(key)
    if not isinstance(value, dict):
        msg = f"{context} is missing {key}"
        raise PayloadError(msg)
    return value


def required_simulation_object_list(
    container: JsonObject,
    key: str,
    *,
    context: str,
) -> list[JsonObject]:
    """Return a required list containing only JSON objects.

    Raises:
        PayloadError: If provider data violates the payload contract.

    """
    value = container.get(key)
    if not isinstance(value, list):
        msg = f"{context} is missing {key}"
        raise PayloadError(msg)
    objects: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            msg = f"{context} {key} must contain only objects"
            raise PayloadError(msg)
        objects.append(item)
    return objects
