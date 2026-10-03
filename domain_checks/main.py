from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import runpy
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from playwright.async_api import Browser, async_playwright

from .alert_transition import update_effective_ok as _update_effective_ok
from .browser_admission import BrowserAdmission
from .browser_launch import launch_options
from .browser_phase_context import BrowserPhaseContext, BrowserProbeState
from .browser_probe_settings import load_synthetic_settings, load_vitals_settings
from .browser_recovery_phase import BrowserRecoveryPhase
from .browser_state import browser_state_snapshot, restore_browser_state
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
from .cycle_history import record_domain_results
from .cycle_startup import ChannelStartup, CycleLimits, external_heartbeat
from .cycle_values import coerce_float as _coerce_float
from .cycle_values import required_int
from .dft_cycle import DftCycle, parse_cycle_config
from .dispatch_client import DispatchConfig
from .dispatch_records import DispatchRecords
from .dispatch_state import dispatch_is_enabled as _dispatch_is_enabled
from .dispatch_workflow import dispatch_prompt_and_forward as _dispatch_prompt_and_forward
from .dns_phase import DnsPhase
from .domain_alerts import route_domain_telegram_alert as _route_domain_telegram_alert
from .domain_entries import (
    DomainEntryConfig,
)
from .domain_entries import (
    format_disabled_domain_line as _format_disabled_domain_line,
)
from .domain_entries import (
    normalize_domain_entries as _normalize_domain_entries,
)
from .domain_observation import DomainProbes, observe_domain
from .domain_polling import DomainPolling
from .domain_result_phase import DomainHealth, DomainResultPhase
from .domain_time import load_timezone as _load_timezone
from .domain_time import parse_disabled_until_ts as _parse_disabled_until_ts
from .event_bus import EventBusOutbox
from .event_bus_delivery import JsonObject
from .heartbeat_phase import HeartbeatObservation, HeartbeatPhase, HeartbeatSchedule
from .heartbeat_settings import load_heartbeat_settings
from .history import prune_history
from .history_migration import migrate_effective_history
from .history_phase_context import HistoryFrame
from .history_settings import load_red_settings, load_slo_settings
from .host_phase import HostPhase
from .host_readings import compute_cpu_used_percent as _compute_cpu_used_percent
from .host_readings import format_browser_health_hint as _format_browser_health_hint
from .host_readings import read_linux_meminfo_kb as _read_linux_meminfo_kb
from .host_thresholds import collect_host_health_violations as _collect_host_health_violations
from .inventory import validate_domain_inventory
from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules
from .meta_phase import CycleTiming, MetaPhase
from .metrics_api_contract import ApiContractCheckResult, run_api_contract_checks
from .metrics_synthetic import run_synthetic_transactions
from .metrics_web_vitals import measure_web_vitals
from .monitor_state import load_monitor_state as _load_monitor_state
from .network_settings import load_dns_settings, load_tls_settings
from .performance import collect_performance_violations as _collect_performance_violations
from .performance_phase import PerformancePhase
from .probe_frame import ProbeDomains, ProbeFrame
from .proxy_observation import ProxyReader
from .proxy_phase import ProxyPhase
from .proxy_settings import load_proxy_settings
from .red_phase import run_red_phase
from .resource_settings import load_host_settings, load_performance_settings
from .service_settings import load_container_settings, load_meta_settings
from .signal_history import SignalHistory
from .slo_phase import run_slo_phase
from .state_storage import write_state_atomic as _write_state_atomic
from .synthetic_phase import SyntheticPhase
from .telegram import TelegramConfig, redact_telegram_response, send_telegram_message
from .tls_phase import TlsPhase
from .vitals_phase import VitalsPhase

# Retained import contract used by repository tests and monitoring_v2.domain_runtime.
__all__ = [
    "DomainEntryConfig", "_collect_host_health_violations", "_collect_performance_violations",
    "_compute_cpu_used_percent", "_parse_disabled_until_ts",
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


























def _build_api_contract_alert_message(
    *,
    failures: list[ApiContractCheckResult],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: API contract checks are failing ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for r in failures[:15]:
        sc = "n/a" if r.status_code is None else str(r.status_code)
        ms = "n/a" if r.elapsed_ms is None else f"{int(round(float(r.elapsed_ms)))}ms"
        err = (r.error or "contract_failed").strip()[:260]
        lines.append(f"- {r.domain} [{r.name}]: {err} status={sc} ({ms}) url={r.url}")
    return "\n".join(lines).strip()


def _build_api_contract_dispatch_prompt(*, failures: list[ApiContractCheckResult]) -> str:
    payload = [
        {
            "domain": r.domain,
            "name": r.name,
            "url": r.url,
            "status_code": r.status_code,
            "elapsed_ms": r.elapsed_ms,
            "error": r.error,
            "details": r.details,
        }
        for r in failures[:30]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected API contract failures (JSON endpoints returning unexpected status/shape/latency).\n\n"
        "Failing checks (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce the failing API calls from the production host (curl -i).\n"
        "2) Determine whether the issue is backend crash, reverse proxy routing, deploy regression, or auth/config.\n"
        "3) Identify the relevant container(s) and inspect logs/health/restarts.\n"
        "4) Provide a clear remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Impacted endpoints\n"
        "- Recommended safe remediation steps\n"
    )






































async def _dispatch_api_contract_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    failures: list[ApiContractCheckResult],
    dispatch_history: list[dict[str, Any]] | None = None,
    dispatch_last: dict[str, dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> None:
    prompt = _build_api_contract_dispatch_prompt(failures=failures)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.api_contract",
        telegram_title="API contract investigation",
        dispatch_state=dispatch_state,
        dispatch_history=dispatch_history,
        dispatch_last=dispatch_last,
        events=events,
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

    api_cfg = cycle_section(config, "api_contract")
    api_enabled = bool(api_cfg.get("enabled", False))
    api_interval_minutes = max(1, required_int(api_cfg.get("interval_minutes", 10)))
    api_timeout_seconds = _coerce_float(api_cfg.get("timeout_seconds", 10.0), default=10.0)
    api_down_after_failures = max(1, required_int(api_cfg.get("down_after_failures", 2)))
    api_up_after_successes = max(1, required_int(api_cfg.get("up_after_successes", 2)))
    api_dispatch_on_degraded = bool(api_cfg.get("dispatch_on_degraded", False))
    api_notify_on_recovery = bool(api_cfg.get("notify_on_recovery", False))

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

    # Track state (persisted if STATE_PATH is mounted) to avoid spamming alerts every minute.
    last_ok: dict[str, bool] = {}
    fail_streak: dict[str, int] = {}
    success_streak: dict[str, int] = {}
    history_by_domain: dict[str, list[list[Any]]] = {}
    disk_state: dict[str, Any] = {}
    cycle_health = CycleHealthState()
    host_observations = cycle_health.host
    signal_history: dict[str, list[list[Any]]] = {}
    dispatch_history: list[dict[str, Any]] = []
    dispatch_last: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    if state_path is not None:
        disk_state = _load_monitor_state(state_path)
        last_ok.update(disk_state.get("last_ok") or {})
        fail_streak.update(disk_state.get("fail_streak") or {})
        success_streak.update(disk_state.get("success_streak") or {})
        history_by_domain = disk_state.get("history") or {}
        signal_history = disk_state.get("signal_history") if isinstance(disk_state.get("signal_history"), dict) else {}
        dispatch_history = disk_state.get("dispatch_history") if isinstance(disk_state.get("dispatch_history"), list) else []
        dispatch_last = disk_state.get("dispatch_last") if isinstance(disk_state.get("dispatch_last"), dict) else {}
        events = disk_state.get("events") if isinstance(disk_state.get("events"), list) else []
        host_observations.last_snapshot = disk_state.get("host_last_snapshot") if isinstance(disk_state.get("host_last_snapshot"), dict) else {}
        history_ok_mode = str(disk_state.get("history_ok_mode") or "").strip().lower()
        if history_ok_mode != "effective" and isinstance(history_by_domain, dict) and history_by_domain:
            # One-time migration: older state files stored per-cycle *observed* ok in history,
            # which made SLO burn-rate alerts extremely noisy (single transient flakes burn budget).
            # Convert stored history to the debounced effective ok stream so SLO/RED align with
            # our domain DOWN alerting definition.
            try:
                history_by_domain = migrate_effective_history(
                    history_by_domain, down_after_failures=down_after_failures,
                    up_after_successes=up_after_successes,
                )
                LOGGER.info(
                    "Migrated history ok mode to effective prev_mode=%s domains=%s",
                    (history_ok_mode or "unknown"),
                    len(history_by_domain),
                )
            except Exception:
                LOGGER.exception("Failed to migrate history ok mode to effective")
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
    state_write_fail_streak = cycle_health.write_fail_streak
    synthetic_last_ok = cycle_health.probes["synthetic"].last_ok
    synthetic_fail_streak = cycle_health.probes["synthetic"].fail_streak
    synthetic_success_streak = cycle_health.probes["synthetic"].success_streak
    synthetic_last_run_ts = cycle_health.probes["synthetic"].last_run_ts
    web_vitals_last_ok = cycle_health.probes["web_vitals"].last_ok
    web_vitals_fail_streak = cycle_health.probes["web_vitals"].fail_streak
    web_vitals_success_streak = cycle_health.probes["web_vitals"].success_streak
    web_vitals_last_run_ts = cycle_health.probes["web_vitals"].last_run_ts
    api_contract_last_ok = cycle_health.probes["api_contract"].last_ok
    api_contract_fail_streak = cycle_health.probes["api_contract"].fail_streak
    api_contract_success_streak = cycle_health.probes["api_contract"].success_streak
    api_contract_last_run_ts = cycle_health.probes["api_contract"].last_run_ts
    event_bus_outbox: EventBusOutbox | None = None
    if event_bus_config is not None:
        raw_outbox = disk_state.get("event_bus_outbox", [])
        if not isinstance(raw_outbox, list):
            raise RuntimeError("Persisted PitchAI Events Bus outbox must be a list")
        event_bus_outbox = EventBusOutbox(event_bus_config, entries=raw_outbox)
        LOGGER.info("Loaded PitchAI Events Bus outbox pending=%s", event_bus_outbox.pending_count)
    active_dispatch_tasks: dict[str, asyncio.Task[None]] = {}
    check_semaphore = asyncio.Semaphore(check_concurrency)
    browser_semaphore = asyncio.Semaphore(browser_concurrency)
    browser_min_mem_available_mb_raw = os.getenv("BROWSER_MIN_MEM_AVAILABLE_MB")
    if browser_min_mem_available_mb_raw is None:
        browser_min_mem_available_mb_raw = config.get("browser_min_mem_available_mb", 2048)
    monitor_state = restore_browser_state(disk_state, browser_min_mem_available_mb_raw)

    def _append_event(kind: str, *, ts: float | None = None, **fields: Any) -> None:
        nonlocal state_write_fail_streak
        entry = {"ts": float(ts) if ts is not None else time.time(), "kind": str(kind)}
        for k, v in fields.items():
            entry[str(k)] = v
        if event_bus_outbox is not None:
            event_bus_outbox.enqueue(
                str(kind),
                occurred_at=float(entry["ts"]),
                details={str(k): v for k, v in fields.items()},
            )
        events.append(entry)
        if len(events) > 10_000:
            del events[: max(0, len(events) - 8000)]
        if event_bus_outbox is not None and state_path is not None:
            try:
                _write_state_atomic(state_path, _build_state_payload())
                state_write_fail_streak = 0
            except Exception as exc:
                state_write_fail_streak = int(state_write_fail_streak) + 1
                LOGGER.warning(
                    "Failed to persist PitchAI Events Bus outbox path=%s error=%s",
                    state_path,
                    exc,
                )

    def _append_history_event(kind: str, timestamp: float, fields: JsonObject) -> None:
        _append_event(kind, ts=timestamp, **fields)

    signal_series = SignalHistory(signal_history)
    _append_signal_sample = signal_series.append
    _prune_signal_history = signal_series.prune

    def _build_state_payload() -> dict[str, Any]:
        # Keep state bounded. We prune time-series histories by timestamp below, but
        # also hard-cap list growth for safety if a corrupt clock or bug bypasses pruning.
        dispatch_history_capped = dispatch_history[-500:]
        events_capped = events[-2000:]
        return {
            "version": 6,
            "history_ok_mode": "effective",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_ok": last_ok,
            "fail_streak": fail_streak,
            "success_streak": success_streak,
            "history": history_by_domain,
            "signal_history": signal_history,
            "dispatch_history": dispatch_history_capped,
            "dispatch_last": dispatch_last,
            "events": events_capped,
            "event_bus_outbox": event_bus_outbox.to_state() if event_bus_outbox else [],
            "dft_web_access": dft_cycle.summary,
            "host_last_snapshot": host_observations.last_snapshot,
            **browser_state_snapshot(monitor_state),
            **cycle_health.snapshot(state_write_fail_streak),
        }

    def _persist_browser_notice() -> None:
        nonlocal state_write_fail_streak
        if state_path is not None:
            try:
                _write_state_atomic(state_path, _build_state_payload())
                state_write_fail_streak = 0
            except Exception as exc:
                state_write_fail_streak = int(state_write_fail_streak) + 1
                LOGGER.warning(
                    "Failed to persist degraded notice timestamp path=%s error=%s",
                    state_path,
                    exc,
                )


    async def _flush_event_bus(http_client: httpx.AsyncClient) -> None:
        if event_bus_outbox is None or event_bus_outbox.pending_count == 0:
            return
        attempts = await event_bus_outbox.flush(http_client)
        for attempt in attempts:
            log = LOGGER.info if attempt.success else LOGGER.warning
            log(
                "PitchAI Events Bus delivery success=%s delivery_id=%s status=%s "
                "event_id=%s error=%s pending=%s",
                attempt.success,
                attempt.delivery_id,
                attempt.status_code,
                attempt.event_id,
                attempt.error,
                event_bus_outbox.pending_count,
            )

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as http_client:
        cycle_channels = CycleChannels(
            http_client, telegram_cfg, dispatch_cfg, dispatch_state,
            DispatchRecords(dispatch_history, dispatch_last, events), active_dispatch_tasks,
        )
        host_phase = HostPhase(host_settings, host_health, host_observations, cycle_channels,
                               _append_history_event, signal_series)
        domain_result_phase = DomainResultPhase(
            DomainHealth(last_ok, fail_streak, success_streak, down_after_failures, up_after_successes),
            entries_by_domain, cycle_channels, _append_history_event,
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
        synthetic_phase = SyntheticPhase(syn_settings, BrowserProbeState(
            synthetic_last_ok, synthetic_fail_streak, synthetic_success_streak, synthetic_last_run_ts),
            lambda inputs: run_synthetic_transactions(**inputs))
        vitals_phase = VitalsPhase(wv_settings, BrowserProbeState(
            web_vitals_last_ok, web_vitals_fail_streak, web_vitals_success_streak, web_vitals_last_run_ts),
            lambda inputs: measure_web_vitals(**inputs))
        if event_bus_outbox is not None:
            _append_event(
                "service_started",
                ts=time.time(),
                interval_seconds=int(interval_seconds),
                monitored_domains=int(len(all_domains) - len(disabled_domains)),
            )
            await _flush_event_bus(http_client)
            if state_path is not None:
                _write_state_atomic(state_path, _build_state_payload())
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
                                                    _persist_browser_notice)

            domain_polling = DomainPolling(check_semaphore, browser_semaphore, http_client, browser_admission,
                                           lambda inputs: check_one_domain(**inputs))
            await browser_admission.ensure(time.time())
            try:
                while True:
                    cycle_started = time.time()
                    cycle_results: dict[str, DomainCheckResult] = {}
                    LOGGER.info("Running check cycle")

                    browser_degraded = False
                    # Ensure the browser is alive at the start of each cycle. This prevents a single
                    # between-cycle crash/close event from degrading *every* domain in the next cycle.
                    await browser_admission.ensure(time.time())

                    now_ts = time.time()
                    disabled_entries = [entry for entry in domain_entries if entry.is_disabled(now_ts)]
                    disabled_set = {entry.domain for entry in disabled_entries}
                    for domain in disabled_set:
                        last_ok.pop(domain, None)
                        fail_streak.pop(domain, None)
                        success_streak.pop(domain, None)
                        history_by_domain.pop(domain, None)
                        synthetic_last_ok.pop(domain, None)
                        synthetic_fail_streak.pop(domain, None)
                        synthetic_success_streak.pop(domain, None)
                        synthetic_last_run_ts.pop(domain, None)
                        web_vitals_last_ok.pop(domain, None)
                        web_vitals_fail_streak.pop(domain, None)
                        web_vitals_success_streak.pop(domain, None)
                        web_vitals_last_run_ts.pop(domain, None)
                        api_contract_last_ok.pop(domain, None)
                        api_contract_fail_streak.pop(domain, None)
                        api_contract_success_streak.pop(domain, None)
                        api_contract_last_run_ts.pop(domain, None)
                        dns_last_ips.pop(domain, None)
                    disabled_lines = sorted(_format_disabled_domain_line(entry, tz) for entry in disabled_entries)
                    enabled_specs = [
                        specs_by_domain[entry.domain] for entry in domain_entries if entry.domain not in disabled_set
                    ]

                    tasks = [asyncio.create_task(domain_polling.run(spec)) for spec in enabled_specs]

                    for fut in asyncio.as_completed(tasks):
                        result = await fut
                        cycle_results[result.domain] = result
                        if bool((result.details or {}).get("browser_infra_error")):
                            browser_degraded = True

                        await domain_result_phase.observe(result, cycle_started)

                    # ------------------------------
                    # Rolling history (SLO/RED inputs)
                    # ------------------------------
                    if not isinstance(history_by_domain, dict):
                        history_by_domain = {}
                    for domain in disabled_set:
                        history_by_domain.pop(domain, None)

                    record_domain_results(history_by_domain, cycle_results, last_ok, ts=cycle_started)

                    try:
                        prune_history(
                            history_by_domain,
                            before_ts=time.time() - float(history_retention_seconds),
                        )
                    except Exception:
                        LOGGER.exception("Failed to prune history")

                    history_frame = HistoryFrame(
                        history_by_domain, alertable_domains, cycle_started,
                        cycle_channels, _append_history_event, signal_series,
                    )
                    await run_slo_phase(history_frame, slo_settings, slo_health)
                    await run_red_phase(history_frame, red_settings, red_health)

                    host_snap, host_violations = await host_phase.run(cycle_started)

                    probe_frame = ProbeFrame(
                        cycle_started, ProbeDomains(enabled_specs, set(entries_by_domain), alertable_domains),
                        cycle_channels, _append_history_event, signal_series,
                    )
                    perf_slow = await performance_phase.run(probe_frame, cycle_results)
                    tls_results = await tls_phase.run(probe_frame)
                    dns_results = await dns_phase.run(probe_frame)

                    # ------------------------------
                    # API contract checks (per-domain)
                    # ------------------------------
                    api_failures_to_alert: list[ApiContractCheckResult] = []
                    api_failures_for_dispatch: list[ApiContractCheckResult] = []
                    if api_enabled and enabled_specs:
                        now_ts = time.time()
                        due_domains = [
                            s
                            for s in enabled_specs
                            if s.api_contract_checks
                            and (now_ts - float(api_contract_last_run_ts.get(s.domain, 0.0))) >= float(api_interval_minutes * 60)
                        ]
                        if due_domains:
                            tasks_by_domain: dict[str, asyncio.Task[list[ApiContractCheckResult]]] = {}
                            for spec in due_domains[:50]:
                                api_contract_last_run_ts[spec.domain] = now_ts
                                tasks_by_domain[spec.domain] = asyncio.create_task(
                                    run_api_contract_checks(
                                        http_client=http_client,
                                        domain=spec.domain,
                                        base_url=spec.url,
                                        checks=spec.api_contract_checks,
                                        timeout_seconds=float(api_timeout_seconds),
                                    )
                                )

                            for domain, task in tasks_by_domain.items():
                                results = await task
                                observed_ok = all(r.ok for r in results) if results else True
                                prev_effective = api_contract_last_ok.get(domain, True)
                                next_effective, next_fail, next_success, alerted_down = _update_effective_ok(
                                    prev_effective_ok=bool(prev_effective),
                                    observed_ok=observed_ok,
                                    fail_streak=int(api_contract_fail_streak.get(domain, 0)),
                                    success_streak=int(api_contract_success_streak.get(domain, 0)),
                                    down_after_failures=api_down_after_failures,
                                    up_after_successes=api_up_after_successes,
                                )
                                api_contract_last_ok[domain] = next_effective
                                api_contract_fail_streak[domain] = next_fail
                                api_contract_success_streak[domain] = next_success

                                if alerted_down:
                                    domain_entry = entries_by_domain[domain]
                                    failures = [r for r in results if not r.ok]
                                    _append_event(
                                        "api_contract_degraded",
                                        ts=float(cycle_started),
                                        domain=domain,
                                        failures=int(len(failures)),
                                        telegram_alert=domain_entry.routes_telegram,
                                        alert_policy=domain_entry.alert_policy.telegram,
                                    )
                                    if domain_entry.routes_telegram:
                                        api_failures_to_alert.extend(failures)
                                        api_failures_for_dispatch.extend(failures)
                                    msg = _build_api_contract_alert_message(
                                        failures=failures,
                                        down_after_failures=api_down_after_failures,
                                        fail_streak=int(next_fail),
                                    )
                                    routed = await _route_domain_telegram_alert(
                                        http_client=http_client,
                                        telegram_cfg=telegram_cfg,
                                        entry=domain_entry,
                                        message=msg,
                                    )
                                    if routed is not None:
                                        ok_all, resps = routed
                                        LOGGER.warning(
                                            "API contract degraded domain=%s sent_ok=%s telegram_last=%s",
                                            domain,
                                            ok_all,
                                            redact_telegram_response(resps[-1] if resps else {}),
                                        )
                                else:
                                    recovered = (not prev_effective) and bool(next_effective)
                                    if recovered:
                                        _append_event(
                                            "api_contract_recovered",
                                            ts=float(cycle_started),
                                            domain=domain,
                                        )
                                    if (
                                        recovered
                                        and api_notify_on_recovery
                                        and entries_by_domain[domain].routes_telegram
                                    ):
                                        ok, resp = await send_telegram_message(
                                            http_client,
                                            telegram_cfg,
                                            f"API contract checks recovered ✅ domain={domain}",
                                        )
                                        LOGGER.info(
                                            "API contract recovery notice sent_ok=%s telegram=%s domain=%s",
                                            ok,
                                            redact_telegram_response(resp),
                                            domain,
                                        )

                            if api_failures_for_dispatch and api_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                if "api_contract" in active_dispatch_tasks and not active_dispatch_tasks["api_contract"].done():
                                    LOGGER.info("Dispatch already running for api_contract; skipping new dispatch")
                                else:
                                    active_dispatch_tasks["api_contract"] = asyncio.create_task(
                                        _dispatch_api_contract_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            failures=api_failures_for_dispatch,
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )

                    # ------------------------------
                    # Docker container health checks
                    # ------------------------------
                    container_issues = await container_phase.run(probe_frame)

                    # ------------------------------
                    # Reverse proxy upstream/failover checks
                    # ------------------------------
                    await proxy_phase.run(probe_frame, cycle_results)

                    # ------------------------------
                    # Synthetic transactions (Playwright step flows)
                    # ------------------------------
                    browser_context = BrowserPhaseContext(probe_frame, entries_by_domain, browser_admission,
                                                          browser_degraded)
                    await synthetic_phase.run(browser_context)
                    await vitals_phase.run(browser_context)

                    await browser_recovery.run(probe_frame, degraded=browser_degraded)

                    cycle_channels.prune_completed()

                    await heartbeat_phase.run(cycle_channels, HeartbeatObservation(
                        cycle_results, entries_by_domain, disabled_lines, host_snap, host_violations,
                        perf_slow if perf_settings.alerts.enabled else None,
                    ))

                    await dft_cycle.observe(now=time.time())

                    try:
                        _prune_signal_history(before_ts=time.time() - float(history_retention_seconds))
                    except Exception:
                        LOGGER.exception("Failed to prune signal history")

                    await _flush_event_bus(http_client)

                    if state_path is not None:
                        try:
                            _write_state_atomic(state_path, _build_state_payload())
                            state_write_fail_streak = 0
                        except Exception as exc:
                            state_write_fail_streak = int(state_write_fail_streak) + 1
                            LOGGER.warning("Failed to write state file path=%s error=%s", state_path, exc)

                    if once:
                        return 0

                    elapsed = time.time() - cycle_started

                    # ------------------------------
                    # Meta-monitoring (monitor pipeline health)
                    # ------------------------------
                    await meta_phase.run(probe_frame, CycleTiming(
                        interval_seconds, elapsed, state_write_fail_streak, browser_admission.browser,
                        check_concurrency, browser_concurrency,
                    ))

                    await _flush_event_bus(http_client)
                    if state_path is not None:
                        try:
                            _write_state_atomic(state_path, _build_state_payload())
                            state_write_fail_streak = 0
                        except Exception as exc:
                            state_write_fail_streak = int(state_write_fail_streak) + 1
                            LOGGER.warning(
                                "Failed to write post-meta state file path=%s error=%s",
                                state_path,
                                exc,
                            )

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
