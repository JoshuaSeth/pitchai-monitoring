# Copyright (c) 2026 PitchAI. All rights reserved.
"""Secret-safe evidence helpers for the monitoring service health contract."""

from __future__ import annotations

import math
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .json_types import JsonValue

_SAFE_FRAGMENT = re.compile(r"\A[A-Za-z0-9_.:+-]{1,64}\Z")
_ERROR_TOKEN = re.compile(r"\A[a-z][a-z0-9_]{0,48}\Z")
_DECIMAL = re.compile(r"\A[+-]?\d+(?:\.\d+)?\Z")
_REDACTED: Final = "redacted"
_UNCLASSIFIED: Final = "unclassified"
_FALLBACK_CLOCK_TICKS: Final = 100.0
_STARTTIME_FIELD_INDEX: Final = 19


def sanitize_fragment(value: JsonValue, *, fallback: str = _REDACTED) -> str:
    """Return a short token that cannot leak credentials or free-form text.

    Args:
        value: Retained evidence that may hold arbitrary text.
        fallback: Token to return when the evidence is not a safe fragment.

    Returns:
        The original fragment when it is already narrow and printable.
    """
    text = value if isinstance(value, str) else str(value)
    return text if _SAFE_FRAGMENT.match(text) else fallback


def error_token(value: JsonValue, *, fallback: str = _UNCLASSIFIED) -> str:
    """Return a role failure classifier derived from retained error text.

    Only text that already looks like a lowercase classifier token is
    published; free-form error messages, URLs and credentials render as
    ``fallback`` so no secret value can reach a health report.

    Args:
        value: Retained error text that may hold arbitrary content.
        fallback: Token published when the text is not a classifier token.

    Returns:
        The lowercase classifier token, or ``fallback``.
    """
    text = value if isinstance(value, str) else str(value)
    return text if _ERROR_TOKEN.match(text) else fallback


def positive_env_integer(name: str, default: int) -> int:
    """Return a positive integer override from the environment.

    Args:
        name: Environment variable that may carry the override.
        default: Value used when the variable is unset or blank.

    Returns:
        The configured positive integer.

    Raises:
        ValueError: If the variable is set to something that is not a
            positive decimal integer.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) <= 0:
        message = f"positive_integer_required={name}"
        raise ValueError(message)
    return int(raw)


def optional_env_text(name: str, default: str) -> str:
    """Return a stripped text override from the environment."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def parse_json_number(value: JsonValue) -> float | None:
    """Return a JSON number, ignoring booleans, text and non-finite values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if math.isfinite(selected) else None


def parse_iso_epoch_seconds(value: JsonValue) -> float | None:
    """Return the epoch seconds of a timezone-aware ISO-8601 stamp.

    Args:
        value: Retained stamp, absent when the state file omits the field.

    Returns:
        The parsed epoch seconds, or ``None`` when the field is absent.

    Raises:
        TypeError: If the stamp is present but not text.
        ValueError: If the stamp is malformed or carries no UTC offset.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        message = f"ISO timestamp must be text, got {type(value).__name__}"
        raise TypeError(message)
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        message = "ISO timestamp must carry an explicit UTC offset"
        raise ValueError(message)
    return parsed.timestamp()


def container_start_epoch(*, now: float, uptime_text: str, pid_one_stat_text: str) -> float | None:
    """Return the epoch at which PID 1 of this container started.

    Args:
        now: Current epoch seconds.
        uptime_text: Contents of ``/proc/uptime``, empty when unavailable.
        pid_one_stat_text: Contents of ``/proc/1/stat``, empty when unavailable.

    Returns:
        The container start epoch, or ``None`` when procfs is unavailable.
    """
    uptime = _first_float(uptime_text)
    start_ticks = _pid_one_start_ticks(pid_one_stat_text)
    if uptime is None or start_ticks is None:
        return None
    started_ago = max(0.0, uptime - start_ticks / _clock_ticks_per_second())
    return now - started_ago


def age_seconds(now: float, timestamp: float) -> float:
    """Return a non-negative age for one observed timestamp."""
    # A clock step backwards must never publish a negative age.
    elapsed = now - timestamp
    return max(0.0, elapsed)


def _first_float(text: str) -> float | None:
    fields = text.split(maxsplit=1)
    if not fields:
        return None
    return _bounded_float(fields[0])


def _bounded_float(text: str) -> float | None:
    normalized = text.strip()
    if not _DECIMAL.match(normalized):
        return None
    selected = float(normalized)
    return selected if math.isfinite(selected) else None


def _clock_ticks_per_second() -> float:
    ticks = _bounded_float(str(os.sysconf("SC_CLK_TCK")))
    if ticks is None or ticks <= 0.0:
        return _FALLBACK_CLOCK_TICKS
    return ticks


def _pid_one_start_ticks(pid_one_stat_text: str) -> float | None:
    # The executable name is parenthesised and may itself contain spaces or
    # parentheses, so field 22 (starttime) is counted from the final ")".
    if ")" not in pid_one_stat_text:
        return None
    fields = pid_one_stat_text.rpartition(")")[2].split()
    if len(fields) <= _STARTTIME_FIELD_INDEX:
        return None
    return _bounded_float(fields[_STARTTIME_FIELD_INDEX])
