# Copyright (c) 2026 PitchAI. All rights reserved.
"""Text and URL normalization shared by domain checks."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_SCRIPT_AND_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")


def normalize_text(value: str) -> str:
    """Normalize whitespace and case for stable text comparisons.

    Returns:
        The normalized text.
    """
    return re.sub(r"\s+", " ", value).strip().lower()


def html_to_visible_text(html: str) -> str:
    """Approximate visible text without script, style, or tag content.

    Returns:
        Normalized visible text.
    """
    without_scripts = _SCRIPT_AND_STYLE_RE.sub(" ", html)
    without_tags = _HTML_TAG_RE.sub(" ", without_scripts)
    return normalize_text(without_tags)


def find_forbidden_text(body_text: str, keywords: list[str]) -> list[str]:
    """Return configured forbidden terms found in normalized body text."""
    return [keyword for keyword in keywords if keyword and keyword.lower() in body_text]


def safe_url(url: str) -> str:
    """Remove query strings from URLs before logging or dispatching them.

    Returns:
        A logging-safe URL without a query string.
    """
    stripped = url.strip()
    if not stripped:
        return stripped
    try:
        parts = urlsplit(stripped)
    except ValueError:
        return stripped[:500]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
