from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


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
        return False, {"ok": False, "error": f"{type(e).__name__}: {e}"}


def redact_telegram_response(data: dict) -> str:
    safe = {"ok": data.get("ok")}
    if isinstance(data.get("result"), dict):
        safe["result"] = {"message_id": data["result"].get("message_id")}
    if data.get("error"):
        safe["error"] = data.get("error")
    return json.dumps(safe, ensure_ascii=False)
