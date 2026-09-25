# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for telegram."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue


@dataclass(frozen=True)
class TelegramConfig:
    """Represent TelegramConfig."""

    bot_token: str
    chat_id: str


TELEGRAM_MAX_MESSAGE_LEN = 3900


def split_telegram_message(text: str, *, max_len: int = TELEGRAM_MAX_MESSAGE_LEN) -> list[str]:
    """Split a Telegram message at bounded newline-aware boundaries.

    Returns:
        Message chunks in delivery order.
    """
    s = (text or "").strip()
    if not s:
        return [""]

    max_len = max(1, int(max_len))
    parts: list[str] = []
    while s:
        if len(s) <= max_len:
            parts.append(s)
            break
        cut = s.rfind("\n", 0, max_len + 1)
        if cut < max_len * 0.6:
            cut = max_len
        chunk = s[:cut].rstrip()
        parts.append(chunk)
        s = s[cut:].lstrip()
    return parts


def _telegram_payload(response: httpx.Response) -> JsonObject:
    data = cast("JsonValue", response.json())
    if not isinstance(data, dict):
        message = "Telegram response was not a JSON object"
        raise TypeError(message)
    return data


async def _post_telegram(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, str],
) -> JsonObject:
    response = await client.post(url, json=payload, timeout=15.0)
    return _telegram_payload(response)


async def send_telegram_message(
    client: httpx.AsyncClient,
    config: TelegramConfig,
    text: str,
) -> tuple[bool, JsonObject]:
    """Send one Telegram message through the Bot API.

    Returns:
        The API success flag and a bounded response payload.
    """
    url = f"https://api.telegram.org/bot{config.bot_token}/sendMessage"
    payload = {"chat_id": config.chat_id, "text": text}
    try:
        data = await _post_telegram(client, url, payload)
    except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        if config.bot_token:
            msg = msg.replace(config.bot_token, "<redacted>")
        return False, {"ok": False, "error": msg}
    return data.get("ok") is True, data


async def send_telegram_message_chunked(
    client: httpx.AsyncClient,
    config: TelegramConfig,
    text: str,
    *,
    max_len: int = TELEGRAM_MAX_MESSAGE_LEN,
) -> tuple[bool, list[JsonObject]]:
    """Send a Telegram message as bounded chunks.

    Returns:
        The aggregate success flag and one response per chunk.
    """
    parts = split_telegram_message(text, max_len=max_len)
    ok_all = True
    responses: list[JsonObject] = []
    for part in parts:
        ok, resp = await send_telegram_message(client, config, part)
        ok_all = ok_all and ok
        responses.append(resp)
    return ok_all, responses


def redact_telegram_response(data: JsonObject) -> str:
    """Render a response without chat, sender, or message content.

    Returns:
        The redacted JSON response.
    """
    safe: JsonObject = {"ok": data.get("ok")}
    result = data.get("result")
    if isinstance(result, dict):
        safe["result"] = {"message_id": result.get("message_id")}
    if data.get("error"):
        safe["error"] = data.get("error")
    return json.dumps(safe, ensure_ascii=False)
