# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed environment readers behind the capacity dashboard settings."""

from __future__ import annotations

import ipaddress
import os
from contextlib import suppress

from .service_failures import FailureCapture

_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def environment_flag(name: str, *, default: bool) -> bool:
    """Read one boolean switch spelled as 1/0, true/false, yes/no, or on/off.

    Returns:
        The switch value, or ``default`` when the variable is unset.

    Raises:
        RuntimeError: If the value is not one of the accepted words.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    word = raw.strip().lower()
    if word not in _TRUE_WORDS | _FALSE_WORDS:
        message = f"{name} must be a boolean"
        raise RuntimeError(message)
    return word in _TRUE_WORDS


def environment_integer(name: str, *, default: int, minimum: int, maximum: int) -> int:
    """Read one bounded integer.

    Returns:
        The integer, or ``default`` when the variable is unset.

    Raises:
        RuntimeError: If the value is not an integer.
    """
    raw = os.getenv(name)
    value = default
    if raw is not None:
        with FailureCapture(ValueError) as failure:
            value = int(raw.strip())
        if failure.error is not None:
            message = f"{name} must be an integer"
            raise RuntimeError(message) from failure.error
    _require_within(name, value, minimum=minimum, maximum=maximum)
    return value


def environment_number(name: str, *, default: float, minimum: float, maximum: float) -> float:
    """Read one bounded floating-point number.

    Returns:
        The number, or ``default`` when the variable is unset.

    Raises:
        RuntimeError: If the value is not a number.
    """
    raw = os.getenv(name)
    value = default
    if raw is not None:
        with FailureCapture(ValueError) as failure:
            value = float(raw.strip())
        if failure.error is not None:
            message = f"{name} must be a number"
            raise RuntimeError(message) from failure.error
    _require_within(name, value, minimum=minimum, maximum=maximum)
    return value


def is_loopback_host(hostname: str | None) -> bool:
    """Report whether a host name is ``localhost`` or a loopback IP literal.

    Returns:
        True only for loopback hosts.
    """
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    with suppress(ValueError):
        return ipaddress.ip_address(hostname).is_loopback
    return False


def _require_within(name: str, value: float, *, minimum: float, maximum: float) -> None:
    if not minimum <= value <= maximum:
        message = f"{name} must be between {minimum} and {maximum}"
        raise RuntimeError(message)
