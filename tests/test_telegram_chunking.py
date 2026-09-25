# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test telegram chunking behavior."""

from __future__ import annotations

from domain_checks.telegram import TELEGRAM_MAX_MESSAGE_LEN, split_telegram_message
from domain_checks.testing import verify

_SMALL_MESSAGE_LIMIT = 500
_EXPECTED_CHUNK_COUNT = 2


def test_split_telegram_message_respects_max_len() -> None:
    """Verify split telegram message respects max len."""
    text = ("line\n" * 2000).strip()
    parts = split_telegram_message(text, max_len=_SMALL_MESSAGE_LIMIT)
    valid_lengths = [0 < len(part) <= _SMALL_MESSAGE_LIMIT for part in parts]
    verify(len(parts) > 1)
    verify(all(valid_lengths))


def test_split_telegram_message_default_limit() -> None:
    """Verify split telegram message default limit."""
    text = "a" * (TELEGRAM_MAX_MESSAGE_LEN + 10)
    parts = split_telegram_message(text)
    verify(len(parts) == _EXPECTED_CHUNK_COUNT)
    verify(len(parts[0]) <= TELEGRAM_MAX_MESSAGE_LEN)
    verify(len(parts[1]) <= TELEGRAM_MAX_MESSAGE_LEN)
