from __future__ import annotations

import argparse
import asyncio
import logging
import os
import runpy
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import yaml
from playwright.async_api import Browser, async_playwright

from .api_contract_phase import ApiContractPhase
from .api_contract_settings import ApiContractSettings
from .dispatch_api_contract import dispatch_api_contract_and_forward as _dispatch_api_contract_and_forward
from .message_api_contract import build_api_contract_alert_message as _build_api_contract_alert_message
from .message_api_contract import build_api_contract_dispatch_prompt as _build_api_contract_dispatch_prompt
from .alert_transition import update_effective_ok as _update_effective_ok
from .browser_admission import BrowserAdmission
from .browser_launch import launch_options
from .browser_probe_settings import load_synthetic_settings, load_vitals_settings
from .browser_recovery_phase import BrowserRecoveryPhase
from .browser_state import restore_browser_state
from .common_check import (
    DomainCheckResult,
    DomainCheckSpec,
    browser_check,
    find_chromium_executable,
    http_get_check,
    load_domain_spec_from_module_dict,
)
from .container_phase import ContainerPhase
from .cycle_channels import CycleChannels
from .cycle_configuration import cycle_section
from .cycle_health_state import CycleHealthState
from .cycle_domain_phase import CycleDomainPhase, CycleInventory
from .cycle_iteration import CycleIteration, CycleParticipants
from .cycle_phases import BrowserPhases, CyclePhases, HistoryPhases, MetricPhases
from .cycle_records import CycleRecords
from .cycle_persistence import CyclePersistence, restore_outbox
from .cycle_startup import ChannelStartup, CycleLimits, external_heartbeat
from .cycle_values import coerce_float as _coerce_float
from .dft_cycle import DftCycle, parse_cycle_config
from .dispatch_records import DispatchRecords
from .dns_phase import DnsPhase
from .domain_entries import (
    DomainEntryConfig,
)
from .domain_entries import (
    normalize_domain_entries as _normalize_domain_entries,
)
from .domain_observation import DomainProbes, observe_domain
from .domain_polling import DomainPolling
from .domain_result_phase import DomainHealth, DomainResultPhase
from .domain_time import load_timezone as _load_timezone
from .domain_time import parse_disabled_until_ts as _parse_disabled_until_ts
from .event_bus_delivery import JsonObject
from .heartbeat_phase import HeartbeatPhase, HeartbeatSchedule
from .heartbeat_settings import load_heartbeat_settings
from .history_settings import load_red_settings, load_slo_settings
from .host_phase import HostPhase
from .host_readings import compute_cpu_used_percent as _compute_cpu_used_percent
from .host_readings import format_browser_health_hint as _format_browser_health_hint
from .host_readings import read_linux_meminfo_kb as _read_linux_meminfo_kb
from .host_thresholds import collect_host_health_violations as _collect_host_health_violations
from .inventory import validate_domain_inventory
from .meta_phase import CycleTiming, MetaPhase
from .metrics_api_contract import run_api_contract_checks
from .metrics_synthetic import run_synthetic_transactions
from .metrics_web_vitals import measure_web_vitals
from .monitor_state import load_monitor_state as _load_monitor_state
from .network_settings import load_dns_settings, load_tls_settings
from .performance import collect_performance_violations as _collect_performance_violations
from .performance_phase import PerformancePhase
from .proxy_observation import ProxyReader
from .proxy_phase import ProxyPhase
from .proxy_settings import load_proxy_settings
from .resource_settings import load_host_settings, load_performance_settings
from .service_settings import load_container_settings, load_meta_settings
from .signal_history import SignalHistory
from .state_storage import write_state_atomic as _write_state_atomic
from .synthetic_phase import SyntheticPhase
from .tls_phase import TlsPhase
from .vitals_phase import VitalsPhase

# Retained import contract used by repository tests and monitoring_v2.domain_runtime.
__all__ = [
    "_build_api_contract_alert_message", "_build_api_contract_dispatch_prompt", "_dispatch_api_contract_and_forward",
    "DomainEntryConfig", "_collect_host_health_violations", "_collect_performance_violations",
    "_compute_cpu_used_percent", "_load_monitor_state", "_parse_disabled_until_ts",
    "check_one_domain", "load_config", "load_domain_spec", "main", "run_loop",
]

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
    browser: Browser | None,
    *,
    browser_semaphore: asyncio.Semaphore,
) -> DomainCheckResult:
    probes = DomainProbes(http_get_check, browser_check)
    return await observe_domain(spec, http_client, browser, browser_semaphore=browser_semaphore, probes=probes)


async def run_loop(config_path: Path, once: bool) -> int:
    config = load_config(config_path)
    validate_domain_inventory(config)
    limits = CycleLimits.read(config)
    interval_seconds = limits.interval
    tolerance_seconds = limits.tolerance
    browser_concurrency = limits.browser_concurrency
    check_concurrency = limits.check_concurrency
    down_after_failures = limits.down_after_failures
    up_after_successes = limits.up_after_successes

    domains_cfg = config.get("domains", [])
    if not isinstance(domains_cfg, list) or not domains_cfg:
        raise ValueError("Config must contain a non-empty 'domains' list")

    channels = ChannelStartup.read(os.environ)
    telegram_cfg = channels.telegram
    event_bus_config = channels.event_bus
    dispatch_cfg = channels.dispatch
    dispatch_state = channels.dispatch_state

    domain_entries = _normalize_domain_entries(domains_cfg)
    entries_by_domain = {entry.domain: entry for entry in domain_entries}
    alertable_domains = {entry.domain for entry in domain_entries if entry.routes_telegram}
    specs_by_domain: dict[str, DomainCheckSpec] = {
        entry.domain: load_domain_spec(entry.raw_entry) for entry in domain_entries
    }
    all_domains = [entry.domain for entry in domain_entries]

    heartbeat_settings = load_heartbeat_settings(config)

    tz = _load_timezone(heartbeat_settings.timezone)
    started_at = datetime.now(tz)
    last_heartbeat_sent: dict[str, str] = {}  # HH:MM -> YYYY-MM-DD

    registry_heartbeat = external_heartbeat(config, os.environ)

    host_settings = load_host_settings(config)

    perf_settings = load_performance_settings(config)

    history_cfg = cycle_section(config, "history")
    history_retention_days = _coerce_float(history_cfg.get("retention_days", 7.0), default=7.0)
    history_retention_days = max(1.0, float(history_retention_days))
    history_retention_seconds = history_retention_days * 86400.0

    slo_settings = load_slo_settings(config)

    tls_settings = load_tls_settings(config)

    dns_settings = load_dns_settings(config)

    red_settings = load_red_settings(config)

    syn_settings = load_synthetic_settings(config)

    wv_settings = load_vitals_settings(config)

    api_settings = ApiContractSettings.read(config)

    container_settings = load_container_settings(config)

    proxy_settings = load_proxy_settings(config)

    meta_settings = load_meta_settings(config)

    chromium_path = find_chromium_executable()
    if not chromium_path:
        raise RuntimeError("Could not find a Chromium/Chrome executable (set CHROMIUM_PATH)")

    now_ts = time.time()
    disabled_domains = [entry.domain for entry in domain_entries if entry.is_disabled(now_ts)]
    LOGGER.info(
        "Starting service monitor domains=%s disabled_domains=%s interval_seconds=%s chromium_path=%s",
        all_domains,
        disabled_domains,
        interval_seconds,
        chromium_path,
    )

    state_path_raw = str(os.getenv("STATE_PATH", "/data/state.json") or "").strip()
    state_path = Path(state_path_raw) if state_path_raw else None
    dft_cycle = DftCycle(parse_cycle_config(config.get("dft_web_access")))

    records = CycleRecords.load(state_path, down_after_failures=down_after_failures,
                                up_after_successes=up_after_successes)
    last_ok = records.domains.last_ok
    fail_streak = records.domains.fail_streak
    success_streak = records.domains.success_streak
    disk_state = records.disk
    cycle_health = CycleHealthState()
    host_observations = cycle_health.host
    host_observations.last_snapshot = records.host_snapshot
    signal_history = records.signals
    dispatch_history = records.activity.dispatch_history
    dispatch_last = records.activity.dispatch_last
    events = records.activity.events
    cycle_health.restore(disk_state)
    host_health = cycle_health.health["host_health"]
    perf_health = cycle_health.health["performance"]
    slo_health = cycle_health.health["slo"]
    tls_health = cycle_health.health["tls"]
    tls_schedule = cycle_health.schedules["tls"]
    dns_health = cycle_health.health["dns"]
    dns_schedule = cycle_health.schedules["dns"]
    dns_last_ips = cycle_health.dns_ips
    red_health = cycle_health.health["red"]
    container_health = cycle_health.health["container_health"]
    container_schedule = cycle_health.schedules["container_health"]
    container_observations = cycle_health.containers
    proxy_health = cycle_health.health["proxy"]
    meta_health = cycle_health.health["meta"]
    event_bus_outbox = restore_outbox(event_bus_config, disk_state)
    active_dispatch_tasks: dict[str, asyncio.Task[None]] = {}
    check_semaphore = asyncio.Semaphore(check_concurrency)
    browser_semaphore = asyncio.Semaphore(browser_concurrency)
    browser_min_mem_available_mb_raw = os.getenv("BROWSER_MIN_MEM_AVAILABLE_MB")
    if browser_min_mem_available_mb_raw is None:
        browser_min_mem_available_mb_raw = config.get("browser_min_mem_available_mb", 2048)
    monitor_state = restore_browser_state(disk_state, browser_min_mem_available_mb_raw)

    persistence = CyclePersistence(state_path, records, cycle_health, monitor_state, dft_cycle, event_bus_outbox)
    signal_series = SignalHistory(signal_history)

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as http_client:
        cycle_channels = CycleChannels(
            http_client, telegram_cfg, dispatch_cfg, dispatch_state,
            DispatchRecords(dispatch_history, dispatch_last, events), active_dispatch_tasks,
        )
        host_phase = HostPhase(host_settings, host_health, host_observations, cycle_channels,
                               persistence.event, signal_series)
        domain_result_phase = DomainResultPhase(
            DomainHealth(last_ok, fail_streak, success_streak, down_after_failures, up_after_successes),
            entries_by_domain, cycle_channels, persistence.event,
        )
        performance_phase = PerformancePhase(perf_settings, perf_health)
        tls_phase = TlsPhase(tls_settings, tls_health, tls_schedule)
        dns_phase = DnsPhase(dns_settings, dns_health, dns_schedule, dns_last_ips)
        container_phase = ContainerPhase(container_settings, container_health, container_schedule, container_observations)
        proxy_phase = ProxyPhase(ProxyReader(proxy_settings, dft_cycle, specs_by_domain), proxy_health)
        meta_phase = MetaPhase(meta_settings, meta_health)
        heartbeat_phase = HeartbeatPhase(heartbeat_settings,
            HeartbeatSchedule(tz, started_at, tolerance_seconds, last_heartbeat_sent),
            registry_heartbeat)
        synthetic_phase = SyntheticPhase(syn_settings, cycle_health.probes["synthetic"],
            lambda inputs: run_synthetic_transactions(**inputs))
        vitals_phase = VitalsPhase(wv_settings, cycle_health.probes["web_vitals"],
            lambda inputs: measure_web_vitals(**inputs))
        api_phase = ApiContractPhase(api_settings, cycle_health.probes["api_contract"], entries_by_domain,
                                     lambda inputs: run_api_contract_checks(**inputs))
        if event_bus_outbox is not None:
            persistence.event("service_started", time.time(), {
                "interval_seconds": int(interval_seconds),
                "monitored_domains": int(len(all_domains) - len(disabled_domains)),
            })
            await persistence.flush(http_client)
            if state_path is not None:
                _write_state_atomic(state_path, persistence.snapshot())
        async with async_playwright() as p:
            async def _launch_browser() -> Browser:
                shm_bytes = 0
                try:
                    st = os.statvfs("/dev/shm")
                    shm_bytes = int(st.f_frsize) * int(st.f_blocks)
                except Exception:
                    shm_bytes = 0
                return await p.chromium.launch(**launch_options(shm_bytes, chromium_path))

            browser_admission = BrowserAdmission(monitor_state, _launch_browser, _read_linux_meminfo_kb)
            browser_recovery = BrowserRecoveryPhase(browser_admission, _format_browser_health_hint,
                                                    partial(persistence.persist, "browser_notice"))

            domain_polling = DomainPolling(check_semaphore, browser_semaphore, http_client, browser_admission,
                                           lambda inputs: check_one_domain(**inputs))
            domain_cycle = CycleDomainPhase(CycleInventory(domain_entries, specs_by_domain, tz), persistence,
                                            browser_admission, domain_polling, domain_result_phase,
                                            history_retention_seconds)
            phases = CyclePhases(domain_cycle, HistoryPhases(slo_settings, slo_health, red_settings, red_health),
                MetricPhases(host_phase, performance_phase, tls_phase, dns_phase, api_phase, container_phase, proxy_phase),
                BrowserPhases(synthetic_phase, vitals_phase, browser_recovery), heartbeat_phase, meta_phase)
            iteration = CycleIteration(CycleParticipants(entries_by_domain, alertable_domains),
                                       cycle_channels, persistence, phases, signal_series)
            await browser_admission.ensure(time.time())
            try:
                while True:
                    cycle_started = time.time()
                    LOGGER.info("Running check cycle")
                    probe_frame = await iteration.run(cycle_started)

                    if once:
                        return 0

                    elapsed = time.time() - cycle_started

                    # ------------------------------
                    # Meta-monitoring (monitor pipeline health)
                    # ------------------------------
                    await meta_phase.run(probe_frame, CycleTiming(
                        interval_seconds, elapsed, cycle_health.write_fail_streak, browser_admission.browser,
                        check_concurrency, browser_concurrency,
                    ))

                    await persistence.flush(http_client)
                    persistence.persist("post_meta")

                    sleep_for = max(0.0, interval_seconds - elapsed)
                    LOGGER.info(
                        "Cycle complete elapsed_seconds=%s sleep_seconds=%s",
                        round(elapsed, 3),
                        round(sleep_for, 3),
                    )
                    await asyncio.sleep(sleep_for)
            finally:
                dft_cycle.close()
                if browser_admission.browser is not None:
                    await browser_admission.browser.close()


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
