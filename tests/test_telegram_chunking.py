from __future__ import annotations

from domain_checks.telegram import TELEGRAM_MAX_MESSAGE_LEN, split_telegram_message


def test_split_telegram_message_respects_max_len() -> None:
    text = ("line\n" * 2000).strip()
    parts = split_telegram_message(text, max_len=500)
    assert len(parts) > 1
    assert all(0 < len(p) <= 500 for p in parts)


def test_split_telegram_message_default_limit() -> None:
    text = "a" * (TELEGRAM_MAX_MESSAGE_LEN + 10)
    parts = split_telegram_message(text)
    assert len(parts) == 2
    assert len(parts[0]) <= TELEGRAM_MAX_MESSAGE_LEN
    assert len(parts[1]) <= TELEGRAM_MAX_MESSAGE_LEN

