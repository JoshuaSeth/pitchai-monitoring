# Copyright (c) 2026 PitchAI. All rights reserved.
"""Text, URL and response predicates shared by domain observations."""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_SCRIPT_AND_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
_SUCCESS_MIN = 200
_SUCCESS_MAX = 300


@dataclass(frozen=True)
class HostExpectation:
    """The final host and original optional suffix predicate."""

    hostname: str
    suffix: str
    ok: bool


def host_expectation(url: str, suffix: str | None) -> HostExpectation:
    """Parse the final host and preserve the existing simple suffix match.

    Returns:
        The normalized host/suffix and their original match decision.
    """
    final_host = (urlsplit(url).hostname or "").lower()
    expected_suffix = (suffix or "").strip().lower()
    ok = not expected_suffix or (bool(final_host) and final_host.endswith(expected_suffix))
    return HostExpectation(final_host, expected_suffix, ok)


def normalize_text(text: str) -> str:
    """Return whitespace-normalized lowercase text."""
    spaced = re.sub(r"\s+", " ", text)
    return spaced.strip().lower()


def html_to_visible_text(html: str) -> str:
    """Remove the existing script/style and tag patterns before normalization.

    Returns:
        The same approximate visible text used by the HTTP check.
    """
    without_scripts = _SCRIPT_AND_STYLE_RE.sub(" ", html)
    without_tags = _HTML_TAG_RE.sub(" ", without_scripts)
    spaced = re.sub(r"\s+", " ", without_tags)
    return spaced.strip().lower()


def safe_url(url: str) -> str:
    """Strip URL query/fragment, retaining the bounded malformed-URL fallback.

    Returns:
        The original trimmed path or at most 500 characters on parse failure.
    """
    text = (url or "").strip()
    if not text:
        return text
    with suppress(Exception):
        parts = urlsplit(text)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return text[:500]


def forbidden_hits(keywords: list[str], body: str) -> list[str]:
    """Retain ordered, case-insensitive hits, including repeated keywords.

    Returns:
        Only nonempty keywords found in the already normalized body.
    """
    populated = [keyword for keyword in keywords if keyword]
    return [keyword for keyword in populated if keyword.lower() in body]


def status_allowed(status: int | None, allowed: list[int] | None) -> bool:
    """Apply explicit status lists or the original successful HTTP interval.

    Returns:
        False for an absent browser response.
    """
    if status is None:
        return False
    if allowed is not None:
        return status in allowed
    return _SUCCESS_MIN <= status < _SUCCESS_MAX
