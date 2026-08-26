from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


TELEGRAM_HELPER_ROOT = Path("/root/code/telegram_agent_server")


def main() -> int:
    try:
        receipt = validate_private_notifier()
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error_code": _safe_error_code(exc)},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def validate_private_notifier() -> dict[str, Any]:
    if not (TELEGRAM_HELPER_ROOT / "main.py").is_file():
        raise RuntimeError("helper_unavailable")
    helper_root = str(TELEGRAM_HELPER_ROOT)
    if helper_root not in sys.path:
        sys.path.insert(0, helper_root)

    from telegram_agent_server import db
    from telegram_agent_server.config import load_settings
    from telegram_agent_server.telegram_api import get_telegram_chat_type

    settings = load_settings()
    if not settings.bot_token:
        raise RuntimeError("bot_unavailable")
    target = settings.route_registry.private_target("seth-ori")

    db.ensure_db_tunnel(settings)
    connection = db.connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  has_table_privilege(
                    current_user,
                    'pitchai_dispatch.telegram_inbound_updates',
                    'SELECT,INSERT,UPDATE'
                  ),
                  has_sequence_privilege(
                    current_user,
                    'pitchai_dispatch.telegram_inbound_updates_id_seq',
                    'USAGE,SELECT'
                  )
                """
            )
            table_ready, sequence_ready = cursor.fetchone()
    finally:
        connection.close()
    if table_ready is not True or sequence_ready is not True:
        raise RuntimeError("delivery_store_privileges_missing")

    live_chat_type = get_telegram_chat_type(
        bot_token=settings.bot_token,
        chat_id=target.chat_id,
    )
    if live_chat_type != "private":
        raise RuntimeError("live_route_not_private")
    return {
        "status": "ready",
        "policy": "personal-first",
        "requester_key": "seth-ori",
        "route_kind": "private",
        "destination_ref": "seth-ori",
        "live_chat_type": live_chat_type,
        "delivery_store_ready": True,
    }


def _safe_error_code(exc: Exception) -> str:
    message = str(exc).casefold()
    if isinstance(exc, (ImportError, ModuleNotFoundError)) or "helper_unavailable" in message:
        return "helper_unavailable"
    if "bot_unavailable" in message:
        return "bot_unavailable"
    if "delivery_store_privileges_missing" in message:
        return "delivery_store_privileges_missing"
    if any(
        marker in message
        for marker in (
            "password authentication failed",
            "server closed the connection unexpectedly",
            "pm database password is not configured",
            "failed to open pm db tunnel",
            "failed to open pm database tunnel",
        )
    ):
        return "delivery_store_unavailable"
    if "route" in message:
        return "private_route_unavailable"
    return f"unexpected_{type(exc).__name__.lower()}"


if __name__ == "__main__":
    raise SystemExit(main())
