# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict environment-reference expansion for monitoring configuration."""

from __future__ import annotations

import os
import re

_ENV_REF_RE = re.compile(r"\$\{([A-Z0-9_]{1,64})\}")


def substitute_env_refs(text: str) -> str:
    """Expand ``${VAR}`` references and require every referenced variable.

    Returns:
        The text with all environment references expanded.

    Raises:
        ValueError: One or more referenced variables are absent.
    """
    source = str(text or "")
    if "${" not in source:
        return source

    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = os.getenv(key)
        if value is None:
            missing.append(key)
            return ""
        return value

    expanded = _ENV_REF_RE.sub(replace, source)
    if missing:
        message = f"missing_env_secrets: {sorted(set(missing))}"
        raise ValueError(message)
    return expanded
