from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import runpy
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, time as dt_time, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from playwright.async_api import Browser, async_playwright
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common_check import (
    DomainCheckResult,
    DomainCheckSpec,
    browser_check,
    find_chromium_executable,
    http_get_check,
    load_domain_spec_from_module_dict,
)
from .history import prune_history
from .browser_probe_settings import load_synthetic_settings, load_vitals_settings
from .service_settings import load_container_settings, load_meta_settings
from .proxy_settings import load_proxy_settings
from .heartbeat_settings import load_heartbeat_settings
from .heartbeat_phase import HeartbeatPhase, HeartbeatSchedule, HeartbeatObservation, ExternalHeartbeat
from .history_settings import load_slo_settings, load_red_settings
from .network_settings import load_tls_settings, load_dns_settings
from .resource_settings import load_host_settings, load_performance_settings
from .cycle_history import record_domain_results
from .history_migration import migrate_effective_history
from .signal_history import SignalHistory
from .browser_launch import launch_options
from .browser_admission import BrowserAdmission
from .browser_recovery_phase import BrowserRecoveryPhase
from .domain_observation import DomainProbes, observe_domain
from .domain_entries import (
    DomainEntryConfig,
    normalize_domain_entries as _normalize_domain_entries,
    format_disabled_domain_line as _format_disabled_domain_line,
)
from .domain_time import (
    parse_disabled_until_ts as _parse_disabled_until_ts,
    parse_hhmm as _parse_hhmm,
    load_timezone as _load_timezone,
)
from .domain_alerts import (
    build_down_alert_message as _build_down_alert_message,
    route_domain_telegram_alert as _route_domain_telegram_alert,
)
from .heartbeat_message import (
    format_uptime as _format_uptime,
    build_heartbeat_message as _build_heartbeat_message,
)
from .dispatch_domain_routes import dispatch_and_forward as _dispatch_and_forward
from .dispatch_workflow import dispatch_prompt_and_forward as _dispatch_prompt_and_forward
from .dispatch_state import (
    dispatch_state_reenable_if_due as _dispatch_state_reenable_if_due,
    dispatch_is_enabled as _dispatch_is_enabled,
    dispatch_disable as _dispatch_disable,
    dispatch_should_notify as _dispatch_should_notify,
)
from .message_templates import build_dispatch_prompt as _build_dispatch_prompt
from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules
from .message_templates import build_meta_dispatch_prompt as _build_meta_dispatch_prompt
from .message_container import build_container_health_dispatch_prompt as _build_container_health_dispatch_prompt
from .message_proxy import build_proxy_dispatch_prompt as _build_proxy_dispatch_prompt
from .host_readings import (
    compute_cpu_used_percent as _compute_cpu_used_percent,
    disk_usage_percent as _disk_usage_percent,
    format_browser_health_hint as _format_browser_health_hint,
    read_linux_meminfo_kb as _read_linux_meminfo_kb,
    read_linux_proc_stat_cpu_total_idle as _read_linux_proc_stat_cpu_total_idle,
)
from .inventory import DomainAlertPolicy, parse_domain_alert_policy, validate_domain_inventory
from .metrics_api_contract import ApiContractCheckResult, run_api_contract_checks
from .metrics_synthetic import run_synthetic_transactions
from .metrics_web_vitals import measure_web_vitals
from .dispatch_client import (
    DispatchConfig,
    dispatch_job,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    get_last_agent_message,
    get_run_log_tail,
    run_ui_url,
    wait_for_terminal_status,
)
from .event_bus import EventBusOutbox, load_event_bus_config
from .telegram import (
    TelegramConfig,
    redact_telegram_response,
    send_telegram_message,
    send_telegram_message_chunked,
)

from .cycle_configuration import cycle_section
from .alert_transition import update_effective_ok as _update_effective_ok
from .health_state import HealthState
from .host_observations import HostObservations
from .host_phase import HostPhase
from .probe_frame import ProbeDomains, ProbeFrame, ProbeSchedule
from .tls_phase import TlsPhase
from .dns_phase import DnsPhase
from .performance_phase import PerformancePhase
from .container_phase import ContainerPhase, ContainerObservations
from .proxy_phase import ProxyPhase
from .proxy_observation import ProxyReader
from .meta_phase import MetaPhase, CycleTiming
from .browser_phase_context import BrowserPhaseContext, BrowserProbeState
from .synthetic_phase import SyntheticPhase
from .vitals_phase import VitalsPhase
from .cycle_channels import CycleChannels
from .event_bus_delivery import JsonObject
from .dispatch_records import DispatchRecords
from .history_phase_context import HistoryFrame
from .slo_phase import run_slo_phase
from .red_phase import run_red_phase
from .cycle_values import (
    coerce_float as _coerce_float,
    coerce_int as _coerce_int,
    coerce_optional_float as _coerce_optional_float,
    required_int,
)
from .dft_cycle import DftCycle, parse_cycle_config
from .monitor_state import load_monitor_state as _load_monitor_state, load_last_ok_state as _load_last_ok_state
from .state_storage import write_state_atomic as _write_state_atomic
from .state_values import (
    coerce_bool_dict as _coerce_bool_dict,
    coerce_int_dict as _coerce_int_dict,
    coerce_float_dict as _coerce_float_dict,
    coerce_str_list_dict as _coerce_str_list_dict,
)


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
    interval_seconds = int(config.get("interval_seconds", 60))
    tolerance_seconds = max(120, interval_seconds * 2)
    browser_concurrency = max(1, int(config.get("browser_concurrency", 3)))
    check_concurrency = max(1, int(config.get("check_concurrency", 25)))
    alerting_cfg = config.get("alerting") or {}
    if not isinstance(alerting_cfg, dict):
        alerting_cfg = {}
    down_after_failures = max(1, required_int(alerting_cfg.get("down_after_failures", 1)))
    up_after_successes = max(1, required_int(alerting_cfg.get("up_after_successes", 1)))

    domains_cfg = config.get("domains", [])
    if not isinstance(domains_cfg, list) or not domains_cfg:
        raise ValueError("Config must contain a non-empty 'domains' list")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID env vars")

    telegram_cfg = TelegramConfig(bot_token=bot_token, chat_id=chat_id)
    event_bus_config = load_event_bus_config()
    if event_bus_config is None:
        LOGGER.warning("PitchAI Events Bus delivery is not configured")
    else:
        LOGGER.info(
            "PitchAI Events Bus delivery configured environment=%s instance=%s",
            event_bus_config.environment,
            event_bus_config.instance,
        )

    dispatch_base_url = os.getenv("PITCHAI_DISPATCH_BASE_URL", "https://dispatch.pitchai.net").strip()
    dispatch_token = os.getenv("PITCHAI_DISPATCH_TOKEN")
    dispatch_model = os.getenv("PITCHAI_DISPATCH_MODEL")
    dispatch_cfg: DispatchConfig | None = None
    dispatch_state: dict[str, Any] = {
        "enabled": True,
        "disabled_reason": None,
        "disabled_until_monotonic": None,
        "last_notify_monotonic": 0.0,
    }
    if dispatch_token and dispatch_token.strip():
        dispatch_cfg = DispatchConfig(
            base_url=dispatch_base_url,
            token=dispatch_token,
            model=(dispatch_model.strip() if dispatch_model and dispatch_model.strip() else None),
        )
    else:
        LOGGER.warning("Missing PITCHAI_DISPATCH_TOKEN; dispatcher escalation disabled")
        dispatch_state["enabled"] = False
        dispatch_state["disabled_reason"] = "missing_token"

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

    external_e2e_cfg = cycle_section(config, "external_e2e")
    external_e2e_enabled = bool(external_e2e_cfg.get("enabled", False))
    external_e2e_base_url = str(
        os.getenv("E2E_REGISTRY_BASE_URL", str(external_e2e_cfg.get("base_url") or ""))
    ).strip()
    external_e2e_token = (
        os.getenv("E2E_REGISTRY_MONITOR_TOKEN", "").strip()
        or os.getenv("E2E_REGISTRY_ADMIN_TOKEN", "").strip()
        or str(external_e2e_cfg.get("monitor_token") or "").strip()
    )
    external_e2e_timeout_seconds = _coerce_float(
        external_e2e_cfg.get("timeout_seconds", 8.0),
        default=8.0,
    )

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
    host_health = HealthState()
    host_observations = HostObservations()
    perf_health = HealthState()
    slo_health = HealthState()
    tls_health = HealthState()
    tls_schedule = ProbeSchedule()
    dns_health = HealthState()
    dns_schedule = ProbeSchedule()
    dns_last_ips: dict[str, list[str]] = {}
    red_health = HealthState()
    synthetic_last_ok: dict[str, bool] = {}
    synthetic_fail_streak: dict[str, int] = {}
    synthetic_success_streak: dict[str, int] = {}
    synthetic_last_run_ts: dict[str, float] = {}
    web_vitals_last_ok: dict[str, bool] = {}
    web_vitals_fail_streak: dict[str, int] = {}
    web_vitals_success_streak: dict[str, int] = {}
    web_vitals_last_run_ts: dict[str, float] = {}
    api_contract_last_ok: dict[str, bool] = {}
    api_contract_fail_streak: dict[str, int] = {}
    api_contract_success_streak: dict[str, int] = {}
    api_contract_last_run_ts: dict[str, float] = {}
    container_health = HealthState()
    container_schedule = ProbeSchedule()
    container_observations = ContainerObservations()
    proxy_health = HealthState()
    meta_health = HealthState()
    state_write_fail_streak = 0
    signal_history: dict[str, list[list[Any]]] = {}
    dispatch_history: list[dict[str, Any]] = []
    dispatch_last: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    browser_degraded_active = False
    browser_degraded_first_seen_ts = 0.0
    browser_launch_last_error: str | None = None
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
        browser_degraded_active = bool(disk_state.get("browser_degraded_active", False))
        try:
            browser_degraded_first_seen_ts = float(disk_state.get("browser_degraded_first_seen_ts") or 0.0)
        except Exception:
            browser_degraded_first_seen_ts = 0.0
        ble = disk_state.get("browser_launch_last_error")
        browser_launch_last_error = str(ble)[:800] if isinstance(ble, str) and ble.strip() else None
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
        host_state = disk_state.get("host_health")
        if isinstance(host_state, dict):
            host_health = HealthState.from_section(host_state)
            host_observations.cpu_prev_total = _coerce_int(host_state.get("cpu_prev_total"), default=0)
            host_observations.cpu_prev_idle = _coerce_int(host_state.get("cpu_prev_idle"), default=0)
        perf_state = disk_state.get("performance")
        if isinstance(perf_state, dict):
            perf_health = HealthState.from_section(perf_state)
        slo_state = disk_state.get("slo")
        if isinstance(slo_state, dict):
            slo_health = HealthState.from_section(slo_state)

        tls_state = disk_state.get("tls")
        if isinstance(tls_state, dict):
            tls_health = HealthState.from_section(tls_state)
            tls_schedule.last_run_ts = _coerce_float(tls_state.get("last_run_ts"), default=0.0)

        dns_state = disk_state.get("dns")
        if isinstance(dns_state, dict):
            dns_health = HealthState.from_section(dns_state)
            dns_schedule.last_run_ts = _coerce_float(dns_state.get("last_run_ts"), default=0.0)
            dns_last_ips = _coerce_str_list_dict(dns_state.get("last_ips"))

        red_state = disk_state.get("red")
        if isinstance(red_state, dict):
            red_health = HealthState.from_section(red_state)

        syn_state = disk_state.get("synthetic")
        if isinstance(syn_state, dict):
            synthetic_last_ok = _coerce_bool_dict(syn_state.get("last_ok"))
            synthetic_fail_streak = _coerce_int_dict(syn_state.get("fail_streak"))
            synthetic_success_streak = _coerce_int_dict(syn_state.get("success_streak"))
            synthetic_last_run_ts = _coerce_float_dict(syn_state.get("last_run_ts"))

        wv_state = disk_state.get("web_vitals")
        if isinstance(wv_state, dict):
            web_vitals_last_ok = _coerce_bool_dict(wv_state.get("last_ok"))
            web_vitals_fail_streak = _coerce_int_dict(wv_state.get("fail_streak"))
            web_vitals_success_streak = _coerce_int_dict(wv_state.get("success_streak"))
            web_vitals_last_run_ts = _coerce_float_dict(wv_state.get("last_run_ts"))

        api_state = disk_state.get("api_contract")
        if isinstance(api_state, dict):
            api_contract_last_ok = _coerce_bool_dict(api_state.get("last_ok"))
            api_contract_fail_streak = _coerce_int_dict(api_state.get("fail_streak"))
            api_contract_success_streak = _coerce_int_dict(api_state.get("success_streak"))
            api_contract_last_run_ts = _coerce_float_dict(api_state.get("last_run_ts"))

        cont_state = disk_state.get("container_health")
        if isinstance(cont_state, dict):
            container_health = HealthState.from_section(cont_state)
            container_schedule.last_run_ts = _coerce_float(cont_state.get("last_run_ts"), default=0.0)
            container_observations.restart_counts = _coerce_int_dict(cont_state.get("restart_counts"))

        proxy_state = disk_state.get("proxy")
        if isinstance(proxy_state, dict):
            proxy_health = HealthState.from_section(proxy_state)

        meta_state = disk_state.get("meta")
        if isinstance(meta_state, dict):
            meta_health = HealthState.from_section(meta_state)
            state_write_fail_streak = _coerce_int(meta_state.get("state_write_fail_streak"), default=0)
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
    try:
        browser_min_mem_available_mb = int(browser_min_mem_available_mb_raw)
    except Exception:
        browser_min_mem_available_mb = 2048
    monitor_state: dict[str, Any] = {
        "browser_degraded_active": bool(browser_degraded_active),
        "browser_degraded_first_seen_ts": float(browser_degraded_first_seen_ts or 0.0),
        "browser_degraded_last_notice_ts": float(disk_state.get("browser_degraded_last_notice_ts") or 0.0),
        "browser_degraded_recover_streak": 0,
        "browser_degraded_notice_min_interval_seconds": 6 * 3600,
        "browser_launch_fail_count": 0,
        "browser_launch_next_try_ts": 0.0,
        "browser_launch_last_error": browser_launch_last_error,
        "browser_min_mem_available_mb": max(0, browser_min_mem_available_mb),
    }

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
            "browser_degraded_active": bool(monitor_state.get("browser_degraded_active", False)),
            "browser_degraded_first_seen_ts": float(monitor_state.get("browser_degraded_first_seen_ts") or 0.0),
            "browser_launch_last_error": (
                str(monitor_state.get("browser_launch_last_error"))[:800]
                if isinstance(monitor_state.get("browser_launch_last_error"), str)
                else None
            ),
            "browser_degraded_last_notice_ts": float(monitor_state.get("browser_degraded_last_notice_ts") or 0.0),
            "host_health": {
                **host_health.to_state(),
                "cpu_prev_total": int(host_observations.cpu_prev_total),
                "cpu_prev_idle": int(host_observations.cpu_prev_idle),
            },
            "performance": {
                **perf_health.to_state(),
            },
            "slo": {
                **slo_health.to_state(),
            },
            "tls": {
                **tls_health.to_state(),
                "last_run_ts": float(tls_schedule.last_run_ts),
            },
            "dns": {
                **dns_health.to_state(),
                "last_run_ts": float(dns_schedule.last_run_ts),
                "last_ips": dns_last_ips,
            },
            "red": {
                **red_health.to_state(),
            },
            "synthetic": {
                "last_ok": synthetic_last_ok,
                "fail_streak": synthetic_fail_streak,
                "success_streak": synthetic_success_streak,
                "last_run_ts": synthetic_last_run_ts,
            },
            "web_vitals": {
                "last_ok": web_vitals_last_ok,
                "fail_streak": web_vitals_fail_streak,
                "success_streak": web_vitals_success_streak,
                "last_run_ts": web_vitals_last_run_ts,
            },
            "api_contract": {
                "last_ok": api_contract_last_ok,
                "fail_streak": api_contract_fail_streak,
                "success_streak": api_contract_success_streak,
                "last_run_ts": api_contract_last_run_ts,
            },
            "container_health": {
                **container_health.to_state(),
                "last_run_ts": float(container_schedule.last_run_ts),
                "restart_counts": container_observations.restart_counts,
            },
            "proxy": {
                **proxy_health.to_state(),
            },
            "meta": {
                **meta_health.to_state(),
                "state_write_fail_streak": int(state_write_fail_streak),
            },
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
        performance_phase = PerformancePhase(perf_settings, perf_health)
        tls_phase = TlsPhase(tls_settings, tls_health, tls_schedule)
        dns_phase = DnsPhase(dns_settings, dns_health, dns_schedule, dns_last_ips)
        container_phase = ContainerPhase(container_settings, container_health, container_schedule, container_observations)
        proxy_phase = ProxyPhase(ProxyReader(proxy_settings, dft_cycle, specs_by_domain), proxy_health)
        meta_phase = MetaPhase(meta_settings, meta_health)
        heartbeat_phase = HeartbeatPhase(heartbeat_settings,
            HeartbeatSchedule(tz, started_at, tolerance_seconds, last_heartbeat_sent),
            ExternalHeartbeat(external_e2e_enabled, external_e2e_base_url, external_e2e_token,
                              external_e2e_timeout_seconds))
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

                    async def _safe_check(spec: DomainCheckSpec) -> DomainCheckResult:
                        async with check_semaphore:
                            try:
                                return await check_one_domain(
                                    spec,
                                    http_client,
                                    browser_admission.browser,
                                    browser_semaphore=browser_semaphore,
                                )
                            except Exception as exc:
                                err = f"{type(exc).__name__}: {exc}"
                                LOGGER.exception("Domain check crashed domain=%s error=%s", spec.domain, err)
                                return DomainCheckResult(
                                    domain=spec.domain,
                                    ok=False,
                                    reason="check_crashed",
                                    details={"error": err},
                                )

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

                    tasks = [asyncio.create_task(_safe_check(spec)) for spec in enabled_specs]

                    for fut in asyncio.as_completed(tasks):
                        result = await fut
                        cycle_results[result.domain] = result
                        if bool((result.details or {}).get("browser_infra_error")):
                            browser_degraded = True

                        domain = result.domain
                        prev_effective = last_ok.get(domain)
                        if prev_effective is None:
                            prev_effective = True

                        next_effective, next_fail, next_success, alerted_down = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=bool(result.ok),
                            fail_streak=int(fail_streak.get(domain, 0)),
                            success_streak=int(success_streak.get(domain, 0)),
                            down_after_failures=down_after_failures,
                            up_after_successes=up_after_successes,
                        )
                        last_ok[domain] = next_effective
                        fail_streak[domain] = next_fail
                        success_streak[domain] = next_success

                        recovered = (not prev_effective) and bool(next_effective)

                        if alerted_down:
                            domain_entry = entries_by_domain[domain]
                            det = result.details or {}
                            _append_event(
                                "domain_down",
                                ts=float(cycle_started),
                                domain=domain,
                                reason=result.reason,
                                status_code=det.get("status_code"),
                                error=(det.get("error")[:800] if isinstance(det.get("error"), str) else None),
                                fail_streak=int(next_fail),
                                telegram_alert=domain_entry.routes_telegram,
                                alert_policy=domain_entry.alert_policy.telegram,
                            )
                            # Transition UP -> DOWN (debounced), or startup DOWN after threshold.
                            enriched = DomainCheckResult(
                                domain=result.domain,
                                ok=result.ok,
                                reason=result.reason,
                                details={
                                    **(result.details or {}),
                                    "fail_streak": next_fail,
                                    "down_after_failures": down_after_failures,
                                },
                            )
                            msg = _build_down_alert_message(enriched)
                            routed = await _route_domain_telegram_alert(
                                http_client=http_client,
                                telegram_cfg=telegram_cfg,
                                entry=domain_entry,
                                message=msg,
                            )
                            if routed is not None:
                                ok_all, resps = routed
                                resp = resps[-1] if resps else {}
                                LOGGER.warning(
                                    "Alert attempt domain=%s sent_ok=%s reason=%s telegram=%s details=%s",
                                    domain,
                                    ok_all,
                                    result.reason,
                                    redact_telegram_response(resp),
                                    enriched.details,
                                )

                            if (
                                domain_entry.routes_telegram
                                and dispatch_cfg
                                and _dispatch_is_enabled(dispatch_cfg, dispatch_state)
                            ):
                                if domain in active_dispatch_tasks and not active_dispatch_tasks[domain].done():
                                    LOGGER.info("Dispatch already running for domain=%s; skipping new dispatch", domain)
                                else:
                                    active_dispatch_tasks[domain] = asyncio.create_task(
                                        _dispatch_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            result=enriched,
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )
                            else:
                                LOGGER.info(
                                    "Dispatch not scheduled domain=%s alertable=%s enabled=%s reason=%s",
                                    domain,
                                    domain_entry.routes_telegram,
                                    bool(dispatch_cfg and dispatch_state.get("enabled")),
                                    dispatch_state.get("disabled_reason"),
                                )
                        else:
                            if recovered:
                                _append_event("domain_up", ts=float(cycle_started), domain=domain)
                            if result.ok is False and prev_effective is True and next_effective is True:
                                LOGGER.warning(
                                    "Domain failing (alert suppressed) domain=%s fail_streak=%s/%s reason=%s details=%s",
                                    domain,
                                    next_fail,
                                    down_after_failures,
                                    result.reason,
                                    result.details,
                                )
                            else:
                                level = logging.INFO if result.ok else logging.WARNING
                                LOGGER.log(
                                    level,
                                    "Domain result domain=%s ok=%s reason=%s details=%s",
                                    domain,
                                    result.ok,
                                    result.reason,
                                    result.details,
                                )

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

                    # Prune completed dispatch tasks to avoid unbounded growth.
                    for domain, task in list(active_dispatch_tasks.items()):
                        if not task.done():
                            continue
                        try:
                            task.result()
                        except Exception:
                            LOGGER.exception("Dispatch task crashed domain=%s", domain)
                        del active_dispatch_tasks[domain]

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
