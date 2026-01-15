from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


TELEGRAM_MAX_MESSAGE_LEN = 3900


def split_telegram_message(text: str, *, max_len: int = TELEGRAM_MAX_MESSAGE_LEN) -> list[str]:
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


async def send_telegram_message(
    client: httpx.AsyncClient, config: TelegramConfig, text: str
) -> tuple[bool, dict]:
    url = f"https://api.telegram.org/bot{config.bot_token}/sendMessage"
    payload = {"chat_id": config.chat_id, "text": text}
    try:
        resp = await client.post(url, json=payload, timeout=15.0)
        data = resp.json()
        return bool(data.get("ok")), data
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if config.bot_token:
            msg = msg.replace(config.bot_token, "<redacted>")
        return False, {"ok": False, "error": msg}


async def send_telegram_message_chunked(
    client: httpx.AsyncClient,
    config: TelegramConfig,
    text: str,
    *,
    max_len: int = TELEGRAM_MAX_MESSAGE_LEN,
) -> tuple[bool, list[dict]]:
    parts = split_telegram_message(text, max_len=max_len)
    ok_all = True
    responses: list[dict] = []
    for part in parts:
        ok, resp = await send_telegram_message(client, config, part)
        ok_all = ok_all and ok
        responses.append(resp)
    return ok_all, responses


def redact_telegram_response(data: dict) -> str:
    safe = {"ok": data.get("ok")}
    if isinstance(data.get("result"), dict):
        safe["result"] = {"message_id": data["result"].get("message_id")}
    if data.get("error"):
        safe["error"] = data.get("error")
    return json.dumps(safe, ensure_ascii=False)
