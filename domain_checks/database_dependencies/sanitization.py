# Copyright (c) 2026 PitchAI. All rights reserved.
"""Defense-in-depth sanitation for database probe evidence."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain_checks.monitoring_contracts.safe_evidence import EvidenceValue

_USERINFO = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@")
_SECRET_PARAMETER = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\s*[=:]\s*[^\s,;]+",
)


def sanitized_excerpt(value: EvidenceValue, *, max_chars: int = 320) -> str:
    """Remove credential-like material and bound one operator excerpt.

    Returns:
        A single-line, sanitized error excerpt.
    """
    cleaned = _USERINFO.sub(r"\1<redacted>@", str(value or ""))
    cleaned = _SECRET_PARAMETER.sub(r"\1=<redacted>", cleaned)
    return " ".join(cleaned.split())[:max_chars]
