from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import runpy
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from playwright.async_api import async_playwright

from domain_checks.common_check import (
    DomainCheckResult,
    DomainCheckSpec,
    browser_check,
    find_chromium_executable,
    http_get_check,
    load_domain_spec_from_module_dict,
)
from domain_checks.dispatch_client import (
    DispatchConfig,
    dispatch_job,
    get_last_agent_message,
    run_ui_url,
    wait_for_terminal_status,
)
from domain_checks.telegram import (
    TelegramConfig,
    redact_telegram_response,
    send_telegram_message,
    send_telegram_message_chunked,
)


LOGGER = logging.getLogger("service-monitoring")

CODEX_CONFIG_TOML = """
# Service Monitoring: Codex escalation config (runner container).
approval_policy = "never"
sandbox_mode = "danger-full-access"
hide_agent_reasoning = true
""".lstrip()


def _docker_cli_install_pre_command() -> str:
    return (
        "command -v docker >/dev/null 2>&1 && exit 0\n"
        "echo '[pre] docker CLI missing; attempting install' >&2\n"
        "if command -v apt-get >/dev/null 2>&1; then\n"
        "  apt-get update >&2\n"
        "  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker.io >&2\n"
        "  rm -rf /var/lib/apt/lists/*\n"
        "  exit 0\n"
        "fi\n"
        "if command -v apk >/dev/null 2>&1; then\n"
        "  apk add --no-cache docker-cli >&2\n"
        "  exit 0\n"
        "fi\n"
        "echo '[pre] No supported package manager found to install docker CLI' >&2\n"
        "exit 0\n"
    )


def load_config(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Config YAML must be a mapping")
    return data


def _domain_plugin_path(domain: str) -> Path:
    return Path(__file__).parent / domain / "check.py"


def load_domain_spec(domain_entry: Any) -> DomainCheckSpec:
    if isinstance(domain_entry, str):
        domain = domain_entry
        inline_check = None
    else:
        domain = str(domain_entry["domain"])
        inline_check = domain_entry.get("check")

    plugin_path = _domain_plugin_path(domain)
    if plugin_path.exists():
        module_vars = runpy.run_path(str(plugin_path))
        return load_domain_spec_from_module_dict(module_vars)

    if isinstance(inline_check, dict):
        return load_domain_spec_from_module_dict({"CHECK": {"domain": domain, **inline_check}})

    raise FileNotFoundError(
        f"Missing domain check module for {domain}: expected {plugin_path} (or inline 'check' in config.yaml)"
    )


def _build_dispatch_prompt(result: DomainCheckResult) -> str:
    details = json.dumps(result.details, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "A monitored domain is DOWN or showing a broken/maintenance page.\n\n"
        f"Domain: {result.domain}\n"
        f"Monitor reason: {result.reason}\n"
        "Monitor details (JSON):\n"
        f"{details}\n\n"
        "Task:\n"
        f"1) Investigate why {result.domain} is not functioning properly on the production host.\n"
        "2) Use Docker to identify the relevant service container(s) and reverse proxy (by name/image/labels/ports).\n"
        "3) Inspect container status, recent restarts, health checks, and logs.\n"
        "4) Check for common root causes: upstream crash-loop, bad deploy, DNS, cert expiry, proxy config, "
        "resource exhaustion, and disk space issues.\n"
        "5) If a fix is safe and targeted (only the relevant service), apply the minimal fix (e.g., restart that "
        "one container) and re-check.\n"
        "6) If a fix is risky or could disrupt other services, do NOT apply it—just explain clearly.\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Actions taken (if any) + commands run\n"
        "- Current status + what to monitor next\n"
    )


async def _dispatch_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    result: DomainCheckResult,
) -> None:
    prompt = _build_dispatch_prompt(result)
    state_key = f"service-monitoring.{result.domain}"
    pre_commands = [_docker_cli_install_pre_command()]

    try:
        bundle, runner = await dispatch_job(
            http_client,
            dispatch_cfg,
            prompt=prompt,
            config_toml=CODEX_CONFIG_TOML,
            state_key=state_key,
            pre_commands=pre_commands,
        )
        LOGGER.info("Dispatch queued domain=%s bundle=%s runner=%s", result.domain, bundle, runner)

        await wait_for_terminal_status(http_client, dispatch_cfg, bundle=bundle)
        msg = await get_last_agent_message(http_client, dispatch_cfg, bundle=bundle)
        ui = run_ui_url(dispatch_cfg.base_url, bundle)
        if not msg:
            ok, resp = await send_telegram_message(
                http_client,
                telegram_cfg,
                f"{result.domain} investigation finished (bundle={bundle}) but no agent message was found. {ui}",
            )
            LOGGER.warning(
                "Dispatch finished no_message domain=%s bundle=%s sent_ok=%s telegram=%s",
                result.domain,
                bundle,
                ok,
                redact_telegram_response(resp),
            )
            return

        header = f"{result.domain} investigation (bundle={bundle})\n{ui}\n\n"
        ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, header + msg)
        LOGGER.info(
            "Dispatch finished domain=%s bundle=%s telegram_ok=%s telegram_last=%s",
            result.domain,
            bundle,
            ok_all,
            redact_telegram_response(resps[-1] if resps else {}),
        )
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("Dispatch failed domain=%s error=%s", result.domain, err)
        await send_telegram_message(
            http_client,
            telegram_cfg,
            f"{result.domain} dispatch escalation FAILED: {err}",
        )


async def check_one_domain(
    spec: DomainCheckSpec,
    http_client: httpx.AsyncClient,
    browser,
) -> DomainCheckResult:
    http_ok, http_details = await http_get_check(spec, http_client)
    if not http_ok:
        return DomainCheckResult(
            domain=spec.domain,
            ok=False,
            reason="http_check_failed",
            details=http_details,
        )

    browser_ok, browser_details = await browser_check(spec, browser)
    if not browser_ok:
        return DomainCheckResult(
            domain=spec.domain,
            ok=False,
            reason="browser_check_failed",
            details={**http_details, **browser_details},
        )

    return DomainCheckResult(
        domain=spec.domain,
        ok=True,
        reason="ok",
        details={**http_details, **browser_details},
    )


async def run_loop(config_path: Path, once: bool) -> int:
    config = load_config(config_path)
    interval_seconds = int(config.get("interval_seconds", 60))

    domains_cfg = config.get("domains", [])
    if not isinstance(domains_cfg, list) or not domains_cfg:
        raise ValueError("Config must contain a non-empty 'domains' list")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID env vars")

    telegram_cfg = TelegramConfig(bot_token=bot_token, chat_id=chat_id)

    dispatch_base_url = os.getenv("PITCHAI_DISPATCH_BASE_URL", "https://dispatch.pitchai.net").strip()
    dispatch_token = os.getenv("PITCHAI_DISPATCH_TOKEN")
    dispatch_model = os.getenv("PITCHAI_DISPATCH_MODEL")
    if not dispatch_token:
        raise RuntimeError("Missing PITCHAI_DISPATCH_TOKEN env var")
    dispatch_cfg = DispatchConfig(
        base_url=dispatch_base_url,
        token=dispatch_token,
        model=(dispatch_model.strip() if dispatch_model and dispatch_model.strip() else None),
    )

    specs: list[DomainCheckSpec] = [load_domain_spec(entry) for entry in domains_cfg]

    chromium_path = find_chromium_executable()
    if not chromium_path:
        raise RuntimeError("Could not find a Chromium/Chrome executable (set CHROMIUM_PATH)")

    LOGGER.info(
        "Starting service monitor domains=%s interval_seconds=%s chromium_path=%s",
        [s.domain for s in specs],
        interval_seconds,
        chromium_path,
    )

    # Track state in-memory to avoid spamming alerts every minute.
    last_ok: dict[str, bool] = {}
    active_dispatch_tasks: dict[str, asyncio.Task[None]] = {}

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as http_client:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                executable_path=chromium_path,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                while True:
                    cycle_started = time.time()
                    LOGGER.info("Running check cycle")

                    tasks = [
                        check_one_domain(spec, http_client, browser)
                        for spec in specs
                    ]

                    for fut in asyncio.as_completed(tasks):
                        result = await fut
                        prev = last_ok.get(result.domain)
                        last_ok[result.domain] = result.ok

                        if (prev is True or prev is None) and result.ok is False:
                            # Transition UP -> DOWN, or startup DOWN.
                            msg = f"{result.domain} is DOWN"
                            ok, resp = await send_telegram_message(http_client, telegram_cfg, msg)
                            LOGGER.warning(
                                "Alert attempt domain=%s sent_ok=%s reason=%s telegram=%s details=%s",
                                result.domain,
                                ok,
                                result.reason,
                                redact_telegram_response(resp),
                                result.details,
                            )

                            if result.domain in active_dispatch_tasks and not active_dispatch_tasks[result.domain].done():
                                LOGGER.info("Dispatch already running for domain=%s; skipping new dispatch", result.domain)
                            else:
                                active_dispatch_tasks[result.domain] = asyncio.create_task(
                                    _dispatch_and_forward(
                                        http_client=http_client,
                                        telegram_cfg=telegram_cfg,
                                        dispatch_cfg=dispatch_cfg,
                                        result=result,
                                    )
                                )
                        else:
                            level = logging.INFO if result.ok else logging.WARNING
                            LOGGER.log(
                                level,
                                "Domain result domain=%s ok=%s reason=%s details=%s",
                                result.domain,
                                result.ok,
                                result.reason,
                                result.details,
                            )

                    # Prune completed dispatch tasks to avoid unbounded growth.
                    for domain, task in list(active_dispatch_tasks.items()):
                        if not task.done():
                            continue
                        try:
                            task.result()
                        except Exception:
                            LOGGER.exception("Dispatch task crashed domain=%s", domain)
                        del active_dispatch_tasks[domain]

                    if once:
                        return 0

                    elapsed = time.time() - cycle_started
                    sleep_for = max(0.0, interval_seconds - elapsed)
                    LOGGER.info(
                        "Cycle complete elapsed_seconds=%s sleep_seconds=%s",
                        round(elapsed, 3),
                        round(sleep_for, 3),
                    )
                    await asyncio.sleep(sleep_for)
            finally:
                await browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="PitchAI Service Domain Monitor")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.yaml")),
        help="Path to YAML config",
    )
    parser.add_argument("--once", action="store_true", help="Run one check cycle and exit")
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Logging level (INFO, WARNING, ...)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Avoid leaking secrets (Telegram token is embedded in the Telegram API URL).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return asyncio.run(run_loop(Path(args.config), once=bool(args.once)))


if __name__ == "__main__":
    raise SystemExit(main())
