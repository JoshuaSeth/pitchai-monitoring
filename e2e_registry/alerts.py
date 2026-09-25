# Copyright (c) 2026 PitchAI. All rights reserved.
"""Human-readable alert and read-only triage message builders."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, NamedTuple

from domain_checks.telegram import TelegramConfig, send_telegram_message_chunked

if TYPE_CHECKING:
    import httpx

    from e2e_registry.models import JsonObject, JsonValue
    from e2e_registry.settings import RegistrySettings

LOGGER = logging.getLogger("e2e-registry")


class FailureAlertDetails(NamedTuple):
    """Stable failure facts shared by Telegram and triage messages."""

    tenant_id: str
    test_id: str
    test_name: str
    test_kind: str | None
    base_url: str
    run_id: str
    fail_streak: int
    down_after_failures: int
    error_kind: str | None
    error_message: str | None
    final_url: str | None
    artifacts: JsonObject | None


def _safe_json(value: JsonValue, *, max_len: int = 20_000) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return encoded if len(encoded) <= max_len else encoded[:max_len] + "\n...truncated..."


def _public_url(settings: RegistrySettings, path: str) -> str:
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def build_failure_telegram_message(
    *,
    settings: RegistrySettings,
    details: FailureAlertDetails,
) -> str:
    """Build the operator-facing Telegram message for a failure transition.

    Returns:
        A complete Telegram alert message.
    """
    lines = [
        "External E2E test is FAILING ❌",
        f"Test: {details.test_name}",
        f"Test ID: {details.test_id}",
        f"Run ID: {details.run_id}",
    ]
    if details.test_kind:
        lines.append(f"Kind: {str(details.test_kind)[:40]}")
    if details.down_after_failures > 1:
        lines.append(
            f"Debounce: fail_streak={int(details.fail_streak)}/{int(details.down_after_failures)}",
        )
    if details.error_kind:
        lines.append(f"Error kind: {str(details.error_kind)[:120]}")
    if details.error_message:
        lines.append(f"Error: {str(details.error_message)[:500]}")
    if details.final_url:
        lines.append(f"Final URL: {str(details.final_url)[:800]}")

    run_link = _public_url(settings, f"/ui/runs/{details.run_id}")
    test_link = _public_url(settings, f"/ui/tests/{details.test_id}")
    lines.extend((f"UI: {run_link}", f"Test: {test_link}"))

    if details.artifacts:
        # Surface a stable artifact link if present.
        names: list[str] = []
        for k in ("failure_screenshot", "trace_zip", "run_log"):
            v = details.artifacts.get(k)
            if isinstance(v, str) and v.strip():
                names.append(k)
        if names:
            lines.append(f"Artifacts: {', '.join(names)}")

    return "\n".join(lines).strip()


def build_recovery_telegram_message(
    *,
    settings: RegistrySettings,
    test_id: str,
    test_name: str,
    run_id: str,
) -> str:
    """Build the operator-facing Telegram message for a recovery transition.

    Returns:
        A complete Telegram recovery message.
    """
    run_link = _public_url(settings, f"/ui/runs/{run_id}")
    return "\n".join(
        [
            "External E2E test RECOVERED ✅",
            f"Test: {test_name}",
            f"Test ID: {test_id}",
            f"Run: {run_link}",
        ],
    ).strip()


def _dispatch_read_only_rules() -> str:
    # Mirror wording in domain_checks/main.py to keep behavior consistent.
    return (
        "IMPORTANT safety rules:\n"
        "- Do NOT restart/stop/recreate any containers or services.\n"
        "- Do NOT deploy, update images, run apt-get, or change configuration files.\n"
        "- Do NOT prune/remove volumes/images/containers.\n"
        "- Only run read-only diagnostics (docker ps/inspect/logs/stats, curl, df, free, uptime, etc.).\n"
        "- If you believe a restart would help, suggest it as a human action but do not execute it.\n"
    )


def build_dispatch_prompt_for_failure(
    *,
    details: FailureAlertDetails,
) -> str:
    """Build a read-only investigation prompt from normalized failure facts.

    Returns:
        A bounded prompt that prohibits mutating triage actions.
    """
    payload: JsonObject = {
        "test_id": details.test_id,
        "test_name": details.test_name,
        "test_kind": details.test_kind,
        "base_url": details.base_url,
        "run_id": details.run_id,
        "error_kind": details.error_kind,
        "error_message": details.error_message,
        "artifacts": details.artifacts or {},
    }
    return (
        "An external developer-submitted end-to-end UI test is failing.\n\n"
        "Failure details (JSON):\n"
        f"{_safe_json(payload)}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Determine whether the failure is a real product regression vs monitoring/infra instability.\n"
        "2) Reproduce from the production host with curl and, if needed, Playwright in headless mode.\n"
        "3) Inspect relevant containers, reverse proxy, logs, and recent deploys.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Reproduction steps\n"
        "- Scope/impact (which service/domain)\n"
        "- Suggested safe next actions\n"
    )


async def maybe_send_failure_alert(
    *,
    http_client: httpx.AsyncClient,
    settings: RegistrySettings,
    msg: str,
) -> None:
    """Send an alert only when Telegram alerting is explicitly configured."""
    if not settings.alerts_enabled:
        return
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        LOGGER.warning("Telegram not configured; skipping alert")
        return
    cfg = TelegramConfig(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    ok_all, _resps = await send_telegram_message_chunked(http_client, cfg, msg)
    LOGGER.info("Telegram alert sent ok=%s", ok_all)
