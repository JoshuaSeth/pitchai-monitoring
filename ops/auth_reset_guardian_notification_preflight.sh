#!/usr/bin/env bash
set -Eeuo pipefail

readonly TELEGRAM_HELPER_ROOT="/root/code/telegram_agent_server"

if [[ ! -r "${TELEGRAM_HELPER_ROOT}/main.py" ]]; then
  printf '{"error_code":"helper_unavailable","status":"failed"}\n'
  exit 1
fi

exec /usr/bin/env -i HOME=/root PATH=/usr/bin:/bin LANG=C.UTF-8 \
  /usr/bin/python3 - "${TELEGRAM_HELPER_ROOT}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


def _error_code(exc: Exception) -> str:
    message = str(exc).casefold()
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
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


def _validate(helper_root: Path) -> dict[str, object]:
    if not (helper_root / "main.py").is_file():
        raise RuntimeError("helper_unavailable")
    sys.path.insert(0, str(helper_root))

    from telegram_agent_server import db
    from telegram_agent_server.config import load_settings
    from telegram_agent_server.telegram_api import get_telegram_chat_type

    settings = load_settings()
    if not settings.bot_token:
        raise RuntimeError("bot_unavailable")
    target = settings.route_registry.private_target("seth-ori")
    if target.kind.value != "private":
        raise RuntimeError("private_route_unavailable")

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
        raise RuntimeError("private_route_unavailable")
    return {
        "delivery_store_ready": True,
        "destination_ref": "seth-ori",
        "live_chat_type": live_chat_type,
        "policy": "personal-first",
        "requester_key": "seth-ori",
        "route_kind": "private",
        "status": "ready",
    }


try:
    result = _validate(Path(sys.argv[1]))
except Exception as exc:
    print(
        json.dumps(
            {"error_code": _error_code(exc), "status": "failed"},
            sort_keys=True,
        )
    )
    raise SystemExit(1) from None

print(json.dumps(result, sort_keys=True))
PY
