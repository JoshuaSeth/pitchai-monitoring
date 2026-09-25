# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define explicit failures for authentication test-fixture contracts."""

from __future__ import annotations

type ContractValue = (
    str
    | int
    | float
    | bool
    | list[ContractValue]
    | dict[str, ContractValue]
    | None
)


class FixtureContractError(AssertionError):
    """A test fixture or decoded test value violated its required shape."""


def required_value[T](value: T | None, *, label: str) -> T:
    """Require an optional test value to be present.

    Returns:
        The required value.

    Raises:
        FixtureContractError: If the value is absent.

    """
    if value is None:
        msg = f"{label} must be present"
        raise FixtureContractError(msg)
    return value


def required_number(value: ContractValue, *, label: str) -> int | float:
    """Require a decoded test value to be numeric but not Boolean.

    Returns:
        The required numeric value.

    Raises:
        FixtureContractError: If the value is not numeric.

    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{label} must be numeric"
        raise FixtureContractError(msg)
    return value


def required_integer(value: ContractValue, *, label: str) -> int:
    """Require a decoded test value to be an integer but not Boolean.

    Returns:
        The required integer value.

    Raises:
        FixtureContractError: If the value is not an integer.

    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{label} must be an integer"
        raise FixtureContractError(msg)
    return value
