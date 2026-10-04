# Copyright (c) 2026 PitchAI. All rights reserved.
"""Original synthetic transaction text bounds and environment substitution."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue

_ENV_REF_RE = re.compile(r"\$\{([A-Z0-9_]{1,64})\}")


def safe_str(value: JsonValue, *, max_len: int = 500) -> str:
    """Return the original truthy-string conversion limited to the requested length."""
    text = str(value or "")
    return text if len(text) <= max_len else text[:max_len]


def substitute_env_refs(text: str) -> str:
    """Replace the existing uppercase placeholders without silently dropping missing values.

    Returns:
        The original text with each supported reference substituted.

    Raises:
        ValueError: One or more referenced environment values is missing.
    """
    text = str(text or "")
    if "${" not in text:
        return text
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = os.getenv(key)
        if value is None:
            missing.append(key)
            return ""
        return value

    substituted = _ENV_REF_RE.sub(replace, text)
    if missing:
        message = f"missing_env_secrets: {sorted(set(missing))}"
        raise ValueError(message)
    return substituted
