# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native monitor CLI and probe bindings for the ordered monitoring cycle."""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio
from playwright.async_api import async_playwright

from .alert_transition import update_effective_ok as _update_effective_ok
from .common_check import (
    browser_check,
    http_get_check,
)
from .config_file import load_config, load_domain_spec
from .cycle_assembly import NativeProbes
from .cycle_preparation import CyclePreparation, CycleResources
from .cycle_runtime import BrowserOperations, CycleRuntime
from .dispatch_api_contract import dispatch_api_contract_and_forward as _dispatch_api_contract_and_forward
from .domain_entries import (
    DomainEntryConfig,
)
from .domain_entries import (
    normalize_domain_entries as _normalize_domain_entries,
)
from .domain_observation import DomainProbes, observe_domain
from .domain_time import parse_disabled_until_ts as _parse_disabled_until_ts
from .host_readings import compute_cpu_used_percent as _compute_cpu_used_percent
from .host_readings import format_browser_health_hint as _format_browser_health_hint
from .host_readings import read_linux_meminfo_kb as _read_linux_meminfo_kb
from .host_thresholds import collect_host_health_violations as _collect_host_health_violations
from .message_api_contract import build_api_contract_alert_message as _build_api_contract_alert_message
from .message_api_contract import build_api_contract_dispatch_prompt as _build_api_contract_dispatch_prompt
from .metrics_api_contract import run_api_contract_checks
from .metrics_synthetic import run_synthetic_transactions
from .metrics_web_vitals import measure_web_vitals
from .monitor_state import load_monitor_state as _load_monitor_state
from .monitor_transport import MonitorHttpClient
from .native_browser import NativeBrowserLauncher
from .performance import collect_performance_violations as _collect_performance_violations

if TYPE_CHECKING:
    import asyncio

    from httpx import AsyncClient
    from playwright.async_api import Browser

    from .common_check import DomainCheckResult, DomainCheckSpec

# Retained import contract used by repository tests and monitoring_v2.domain_runtime.
__all__ = [
    "DomainEntryConfig",
    "_build_api_contract_alert_message",
    "_build_api_contract_dispatch_prompt",
    "_collect_host_health_violations",
    "_collect_performance_violations",
    "_compute_cpu_used_percent",
    "_dispatch_api_contract_and_forward",
    "_load_monitor_state",
    "_normalize_domain_entries",
    "_parse_disabled_until_ts",
    "_update_effective_ok",
    "check_one_domain",
    "load_config",
    "load_domain_spec",
    "main",
    "run_loop",
]

LOGGER = logging.getLogger("service-monitoring")


async def check_one_domain(
    spec: DomainCheckSpec,
    http_client: AsyncClient,
    browser: Browser | None,
    *,
    browser_semaphore: asyncio.Semaphore,
) -> DomainCheckResult:
    """Return the original HTTP/browser result under existing semaphore admission."""
    probes = DomainProbes(http_get_check, browser_check)
    return await observe_domain(spec, http_client, browser, browser_semaphore=browser_semaphore, probes=probes)


async def run_loop(config_path: Path, *, once: bool) -> int:
    """Run the native monitor with the configured inventory and retained records.

    Returns:
        Zero after one completed cycle; repeated mode retains its existing schedule.
    """
    prepared = CyclePreparation.read(config_path)
    resources = CycleResources.load(prepared)
    async with MonitorHttpClient() as http_client:
        probes: NativeProbes[Browser] = NativeProbes(lambda inputs: run_synthetic_transactions(**inputs),
                              lambda inputs: measure_web_vitals(**inputs),
                              lambda inputs: run_api_contract_checks(**inputs))
        runtime: CycleRuntime[Browser] = CycleRuntime.bind(prepared, resources, http_client, probes)
        await runtime.record_startup()
        async with async_playwright() as playwright:
            launcher = NativeBrowserLauncher(playwright, prepared.browser.executable)
            operations: BrowserOperations[Browser] = BrowserOperations(
                                           launcher.launch, _read_linux_meminfo_kb, _format_browser_health_hint,
                                           lambda inputs: check_one_domain(**inputs))
            return await runtime.browser_runner(operations).run(once=once)


@dataclass
class MonitorArguments(argparse.Namespace):
    """Typed values supplied by the existing command-line argument parser."""

    config: str = str(Path(__file__).with_name("config.yaml"))
    once: bool = False
    log_level: str = "INFO"


def main() -> int:
    """Own the CLI event loop with the explicit asyncio backend.

    Returns:
        The native loop exit status without starting a nested event loop.
    """
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
    args = parser.parse_args(namespace=MonitorArguments())

    logging.basicConfig(
        level=cast("int | str", getattr(logging, args.log_level.upper(), logging.INFO)),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Avoid leaking secrets (Telegram token is embedded in the Telegram API URL).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return anyio.run(partial(run_loop, Path(args.config), once=args.once), backend="asyncio")


if __name__ == "__main__":
    raise SystemExit(main())
