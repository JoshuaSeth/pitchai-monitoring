# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry request scalars with the existing aliases and error responses."""

from __future__ import annotations

from pathlib import Path
from typing import Final

_MAX_EMAIL_LENGTH: Final = 254
_MAX_FILENAME_LENGTH: Final = 120
_KINDS: Final = {"stepflow", "playwright_python", "puppeteer_js"}
_KIND_ALIASES: Final = {
    "stepflow": "stepflow", "yaml": "stepflow", "yml": "stepflow",
    "playwright-python": "playwright_python", "playwright_python": "playwright_python",
    "pw_python": "playwright_python", "puppeteer-js": "puppeteer_js",
    "puppeteer_js": "puppeteer_js", "pptr": "puppeteer_js",
}
_MIN_EMAIL_CHARACTER: Final = 33
_MAX_EMAIL_CHARACTER: Final = 126


def normalize_pitchai_email(raw_email: str | None) -> str | None:
    """Normalize the exact internal identity domain without trimming input.

    Returns:
        The lower-case identity or None for a malformed/unapproved identity.
    """
    if raw_email is None or raw_email != raw_email.strip() or len(raw_email) > _MAX_EMAIL_LENGTH:
        return None
    email = raw_email.lower()
    local_part, separator, domain = email.rpartition("@")
    if email.count("@") != 1 or separator != "@" or not local_part or domain != "pitchai.net":
        return None
    if any(ord(character) < _MIN_EMAIL_CHARACTER or ord(character) > _MAX_EMAIL_CHARACTER for character in email):
        return None
    return email


def normalize_test_kind(kind: str) -> str:
    """Resolve the existing StepFlow, Playwright and Puppeteer aliases.

    Returns:
        The stored kind or the existing empty invalid-kind sentinel.
    """
    text = str(kind or "").strip().lower()
    normalized = _KIND_ALIASES.get(text, text)
    return normalized if normalized in _KINDS else ""


def safe_filename(name: str, *, default: str) -> str:
    """Keep the filename-only upload spelling and length boundary.

    Returns:
        The sanitized name or the caller's kind-specific default.
    """
    base = Path(str(name or "")).name
    cleaned = "".join(character for character in base if character.isalnum() or character in {"-", "_", ".", "+"})
    return cleaned[:_MAX_FILENAME_LENGTH].strip(".") or default
