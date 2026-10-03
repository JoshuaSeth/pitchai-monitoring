# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed JSON contracts for the unchanged legacy Telegram callables."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from . import telegram

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from httpx import AsyncClient

    from .event_bus_delivery import JsonObject
    from .telegram import TelegramConfig

type SendNotice = Callable[[AsyncClient, TelegramConfig, str], Awaitable[tuple[bool, JsonObject]]]
type SendChunks = Callable[[AsyncClient, TelegramConfig, str], Awaitable[tuple[bool, list[JsonObject]]]]
type RedactResponse = Callable[[JsonObject], str]

# These functions return JSON from the existing transport; they are the same
# callable objects, with no route, retry, client allocation or dispatch added.
send_telegram_message = cast("SendNotice", telegram.send_telegram_message)
send_telegram_message_chunked = cast("SendChunks", telegram.send_telegram_message_chunked)
redact_telegram_response = cast("RedactResponse", telegram.redact_telegram_response)
