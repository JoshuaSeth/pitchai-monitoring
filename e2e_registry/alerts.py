from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from domain_checks.dispatch_client import DispatchConfig, dispatch_job, run_ui_url, wait_for_terminal_status, get_run_log_tail
from domain_checks.dispatch_client import extract_last_agent_message_from_exec_log, extract_last_error_message_from_exec_log
from domain_checks.telegram import TelegramConfig, send_telegram_message_chunked
from e2e_registry.settings import RegistrySettings


LOGGER = logging.getLogger("e2e-registry")


def _safe_json(obj: Any, *, max_len: int = 20_000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)
    except Exception:
        s = str(obj)
    return s if len(s) <= max_len else s[:max_len] + "\n...truncated..."


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
    tenant_id: str,
    test_id: str,
    test_name: str,
    run_id: str,
    fail_streak: int,
    down_after_failures: int,
    error_kind: str | None,
    error_message: str | None,
    final_url: str | None,
    artifacts: dict[str, Any] | None,
) -> str:
    lines = ["External E2E test is FAILING ❌", f"Test: {test_name}", f"Test ID: {test_id}", f"Run ID: {run_id}"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={int(fail_streak)}/{int(down_after_failures)}")
    if error_kind:
        lines.append(f"Error kind: {str(error_kind)[:120]}")
    if error_message:
        lines.append(f"Error: {str(error_message)[:500]}")
    if final_url:
        lines.append(f"Final URL: {str(final_url)[:800]}")

    run_link = _public_url(settings, f"/ui/runs/{run_id}")
    test_link = _public_url(settings, f"/ui/tests/{test_id}")
    lines.append(f"UI: {run_link}")
    lines.append(f"Test: {test_link}")

    if artifacts and isinstance(artifacts, dict):
        # Surface a stable artifact link if present.
        names = []
        for k in ("failure_screenshot", "trace_zip", "run_log"):
            v = artifacts.get(k)
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
    run_link = _public_url(settings, f"/ui/runs/{run_id}")
    return "\n".join(
        [
            "External E2E test RECOVERED ✅",
            f"Test: {test_name}",
            f"Test ID: {test_id}",
            f"Run: {run_link}",
        ]
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
    test_id: str,
    test_name: str,
    base_url: str,
    run_id: str,
    error_kind: str | None,
    error_message: str | None,
    artifacts: dict[str, Any] | None,
) -> str:
    payload = {
        "test_id": test_id,
        "test_name": test_name,
        "base_url": base_url,
        "run_id": run_id,
        "error_kind": error_kind,
        "error_message": error_message,
        "artifacts": artifacts or {},
    }
    return (
        "An external developer-submitted end-to-end UI test (Playwright StepFlow) is failing.\n\n"
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
    if not settings.alerts_enabled:
        return
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        LOGGER.warning("Telegram not configured; skipping alert")
        return
    cfg = TelegramConfig(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    ok_all, _resps = await send_telegram_message_chunked(http_client, cfg, msg)
    LOGGER.info("Telegram alert sent ok=%s", ok_all)


async def maybe_dispatch_failure_investigation(
    *,
    http_client: httpx.AsyncClient,
    settings: RegistrySettings,
    prompt: str,
) -> None:
    if not settings.dispatch_enabled:
        return
    if not settings.dispatch_token:
        LOGGER.warning("Dispatcher token missing; skipping dispatch")
        return

    cfg = DispatchConfig(
        base_url=settings.dispatch_base_url,
        token=settings.dispatch_token,
        model=(settings.dispatch_model or None),
        poll_interval_seconds=5.0,
        max_wait_seconds=20 * 60,
        log_tail_bytes=250_000,
    )

    config_toml = "\n".join(
        [
            'approval_policy = "never"',
            'sandbox_mode = "danger-full-access"',
            "hide_agent_reasoning = true",
            "",
        ]
    )

    bundle, _runner = await dispatch_job(http_client, cfg, prompt=prompt, config_toml=config_toml, state_key="e2e-registry.failure")
    status = await wait_for_terminal_status(http_client, cfg, bundle=bundle)
    queue_state = str(status.get("queue_state") or "")
    ui = run_ui_url(cfg.base_url, bundle)

    tail = await get_run_log_tail(http_client, cfg, bundle=bundle)
    msg = extract_last_agent_message_from_exec_log(tail)
    if msg:
        LOGGER.info("Dispatch completed state=%s ui=%s last_msg=%s", queue_state, ui, msg[:200])
        await maybe_send_failure_alert(
            http_client=http_client,
            settings=settings,
            msg="\n".join(["Dispatcher triage completed:", ui, "", msg]).strip(),
        )
        return

    if queue_state != "processed":
        err = extract_last_error_message_from_exec_log(tail) or ""
        await maybe_send_failure_alert(
            http_client=http_client,
            settings=settings,
            msg=f"Dispatcher triage failed state={queue_state} ui={ui}\nError: {err[:500]}",
        )

