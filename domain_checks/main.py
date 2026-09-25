# Copyright (c) 2026 PitchAI. All rights reserved.
"""CLI composition root and stable public monitor compatibility surface."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

from domain_checks.common_check import (
    browser_check,
    http_get_check,
)
from domain_checks.monitor_checks import CheckDependencies
from domain_checks.monitor_checks import check_one_domain as execute_domain_check
from domain_checks.monitor_domains import (
    load_config,
    load_domain_spec,
    normalize_domain_entries,
    parse_disabled_until_ts,
)
from domain_checks.monitor_domains import (
    route_domain_telegram_alert as execute_domain_alert_route,
)
from domain_checks.monitor_host import compute_cpu_used_percent
from domain_checks.monitor_host_policy import collect_host_health_violations
from domain_checks.monitor_performance import collect_performance_violations
from domain_checks.monitor_service import ServiceDependencies, run_monitor
from domain_checks.monitor_state import load_monitor_state, update_effective_ok
from domain_checks.telegram import (
    send_telegram_message_chunked,
)

if TYPE_CHECKING:
    import httpx
    from playwright.async_api import Browser

    from domain_checks.common_check import DomainCheckResult, DomainCheckSpec
    from domain_checks.monitor_domains import DomainEntryConfig
    from domain_checks.telegram import TelegramConfig
    from domain_checks.types import JsonObject

LOGGER = logging.getLogger("service-monitoring")

__all__ = [
    "check_one_domain",
    "collect_host_health_violations",
    "collect_performance_violations",
    "compute_cpu_used_percent",
    "load_config",
    "load_domain_spec",
    "load_monitor_state",
    "main",
    "normalize_domain_entries",
    "parse_disabled_until_ts",
    "route_domain_telegram_alert",
    "run_loop",
    "update_effective_ok",
]


async def route_domain_telegram_alert(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    entry: DomainEntryConfig,
    message: str,
) -> tuple[bool, list[JsonObject]] | None:
    """Route a domain alert through the patchable Telegram dependency.

    Returns:
        The chunked delivery result, or ``None`` for dashboard-only policy.
    """
    sender = send_telegram_message_chunked
    return await execute_domain_alert_route(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        entry=entry,
        message=message,
        send_chunks=sender,
    )


async def check_one_domain(
    spec: DomainCheckSpec,
    http_client: httpx.AsyncClient,
    browser: Browser | None,
    browser_semaphore: asyncio.Semaphore,
) -> DomainCheckResult:
    """Compose patchable HTTP and browser dependencies for one domain.

    Returns:
        The normalized HTTP/browser result.
    """
    dependencies = CheckDependencies(
        http_check=http_get_check,
        browser_check=browser_check,
    )
    return await execute_domain_check(
        spec,
        http_client,
        browser,
        browser_semaphore=browser_semaphore,
        dependencies=dependencies,
    )


async def run_loop(config_path: Path, *, once: bool) -> int:
    """Compose stable hooks and run the monitor service.

    Returns:
        Zero after an explicitly requested single cycle.
    """
    dependencies = ServiceDependencies(
        checker=check_one_domain,
        send_chunks=send_telegram_message_chunked,
    )
    return await run_monitor(config_path, once=once, dependencies=dependencies)


class _CliArgs(argparse.Namespace):
    config: str = ""
    once: bool = False
    log_level: str = ""

    def config_path(self) -> Path:
        """Return the configured monitor path."""
        return Path(self.config)

    def logging_level(self) -> int:
        """Return the validated configured logging level."""
        return _log_level(self.log_level)


def _log_level(value: str) -> int:
    normalized = value.strip().upper()
    level = logging.getLevelNamesMapping().get(normalized)
    if isinstance(level, int):
        return level
    message = f"Unknown logging level: {value}"
    raise ValueError(message)


def main() -> int:
    """Parse CLI options and own the top-level asyncio runner.

    Returns:
        The monitor service exit code.
    """
    parser = argparse.ArgumentParser(description="PitchAI Service Domain Monitor")
    _ = parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.yaml")),
        help="Path to YAML config",
    )
    _ = parser.add_argument("--once", action="store_true", help="Run one check cycle and exit")
    _ = parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Logging level (INFO, WARNING, ...)",
    )
    args = cast("_CliArgs", parser.parse_args())
    logging.basicConfig(
        level=args.logging_level(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    with asyncio.Runner() as runner:
        return runner.run(run_loop(args.config_path(), once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
