from __future__ import annotations

import argparse
import asyncio
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
from domain_checks.telegram import TelegramConfig, redact_telegram_response, send_telegram_message


LOGGER = logging.getLogger("service-monitoring")


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
