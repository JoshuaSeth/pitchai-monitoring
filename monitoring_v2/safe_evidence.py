# Copyright (c) 2026 PitchAI. All rights reserved.
"""Sanitize bounded monitoring evidence before it reaches retained state or UI."""

from __future__ import annotations

import html
import re
from typing import Protocol, cast, override
from urllib.parse import unquote

from .json_types import JsonValue


class EvidenceText(Protocol):
    """A boundary value that has a deliberate text representation."""

    @override
    def __str__(self) -> str:
        """Return the value's deliberate text representation."""
        raise NotImplementedError

    @override
    def __repr__(self) -> str:
        """Return the value's deliberate debug representation."""
        raise NotImplementedError


type EvidenceValue = JsonValue | bytes | bytearray | memoryview | BaseException | EvidenceText

_SCRIPT_AND_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_IPV4_RE = re.compile(r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
_PAYMENT_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")
_PRIVATE_PATH_RE = re.compile(
    r"""
    (?:\b[A-Z]:\\(?:Users|Windows|ProgramData)\\[^\s,;]+
    |/(?:home|root|Users|etc|var/lib)/[^\s,;]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_AUTH_RE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"""
    (["']?\b(?:api[_-]?key|authorization|cookie|password|passwd|secret|session|token)
    ["']?\s*[:=]\s*)["']?[^\s,;}"']{3,}
    """,
    re.IGNORECASE | re.VERBOSE,
)
_PRIVATE_ASSIGNMENT_RE = re.compile(
    r"""
    (["']?\b(?:address|email|name|first[_-]?name|last[_-]?name|full[_-]?name|phone
    |user(?:name)?)["']?\s*[:=]\s*)["']?[^\s,;}"']{2,}
    """,
    re.IGNORECASE | re.VERBOSE,
)
_UUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
)
_LONG_OPAQUE_RE = re.compile(
    r"""
    \b(?=[A-Za-z0-9_+/=-]{24,}\b)(?=[A-Za-z0-9_+/=-]*[A-Za-z])
    (?=[A-Za-z0-9_+/=-]*\d)[A-Za-z0-9_+/=-]+\b
    """,
    re.VERBOSE,
)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_PUBLIC_URL_RE = re.compile(
    r"""
    ^(?P<scheme>https?)://(?P<authority>[A-Za-z0-9.-]+(?::\d{1,5})?)
    (?P<path>/[^?#\s]*)?(?:[?#].*)?$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_STRUCTURED_TEXT_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/problem+json",
        "application/xml",
        "application/problem+xml",
        "text/xml",
    },
)


def safe_public_url(value: EvidenceValue, *, max_chars: int = 300) -> str | None:
    """Return an HTTP(S) URL without query, fragment, credentials, or private path IDs.

    Returns:
        A bounded safe URL, or None when the input is not a public URL shape.
    """
    raw = "" if value is None else str(value).strip()
    match = _PUBLIC_URL_RE.fullmatch(raw)
    if match is None:
        return None
    safe_segments: list[str] = []
    for raw_segment in (match.group("path") or "/").split("/"):
        decoded = unquote(raw_segment)
        private_segment = (
            decoded in {".", ".."}
            or _EMAIL_RE.search(decoded) is not None
            or _JWT_RE.search(decoded) is not None
            or _UUID_RE.search(decoded) is not None
            or _LONG_OPAQUE_RE.search(decoded) is not None
            or re.fullmatch(r"\d{9,}", decoded) is not None
        )
        safe_segments.append("redacted" if private_segment else raw_segment)
    path = "/".join(safe_segments) or "/"
    cleaned = f"{match.group('scheme').lower()}://{match.group('authority')}{path}"
    return cleaned[: max(1, max_chars)]


def safe_text_excerpt(value: EvidenceValue, *, max_chars: int = 360) -> str | None:
    """Return bounded visible text with conservative private-data redaction.

    Returns:
        Sanitized text, or None when no displayable text remains.
    """
    raw = "" if value is None else str(value)
    if not raw.strip():
        return None
    cleaned = html.unescape(_SCRIPT_AND_STYLE_RE.sub(" ", raw))
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)

    def _strip_url_query(match: re.Match[str]) -> str:
        safe_url = safe_public_url(match.group(0))
        return safe_url or "[redacted url]"

    cleaned = _URL_RE.sub(_strip_url_query, cleaned)
    cleaned = _JWT_RE.sub("[redacted jwt]", cleaned)
    cleaned = _AUTH_RE.sub("[redacted authorization]", cleaned)
    cleaned = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}[redacted]", cleaned)
    cleaned = _PRIVATE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}[redacted]", cleaned)
    cleaned = _EMAIL_RE.sub("[redacted email]", cleaned)
    cleaned = _UUID_RE.sub("[redacted id]", cleaned)
    cleaned = _IPV4_RE.sub("[redacted ip]", cleaned)
    cleaned = _PHONE_RE.sub("[redacted phone]", cleaned)
    cleaned = _PAYMENT_CARD_RE.sub("[redacted number]", cleaned)
    cleaned = _PRIVATE_PATH_RE.sub("[redacted path]", cleaned)
    cleaned = _LONG_OPAQUE_RE.sub("[redacted value]", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return None
    limit = max(40, max_chars)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def safe_response_excerpt(
    value: EvidenceValue,
    *,
    content_type: EvidenceValue,
    max_chars: int = 360,
) -> str | None:
    """Sanitize bounded evidence only for human-readable response types.

    Returns:
        Sanitized response text, or None for binary and empty responses.
    """
    raw_type = "" if content_type is None else str(content_type)
    normalized_type = raw_type.split(";", 1)[0].strip().lower()
    is_structured_text = (
        normalized_type.startswith("text/")
        or normalized_type in _STRUCTURED_TEXT_CONTENT_TYPES
        or normalized_type.endswith(("+json", "+xml"))
    )
    if not is_structured_text:
        return None
    raw = "" if value is None else str(value)
    inspection_limit = max(4_096, max_chars * 8)
    return safe_text_excerpt(raw[:inspection_limit], max_chars=max_chars)


def safe_list(value: JsonValue, *, max_items: int = 12, max_chars: int = 160) -> list[str]:
    """Return a bounded list of sanitized strings.

    Returns:
        Sanitized non-empty list entries.
    """
    if not isinstance(value, list):
        return []
    raw_items = cast("list[object]", value)
    items: list[str] = []
    for raw in raw_items[: max(0, max_items)]:
        cleaned = safe_text_excerpt(raw, max_chars=max_chars)
        if cleaned:
            items.append(cleaned)
    return items
