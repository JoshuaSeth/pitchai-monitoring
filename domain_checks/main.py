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
from .history import append_sample, prune_history
from .browser_launch import launch_options
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
from .dispatch_domain_routes import dispatch_host_health_and_forward as _dispatch_host_health_and_forward
from .dispatch_domain_routes import dispatch_performance_and_forward as _dispatch_performance_and_forward
from .dispatch_domain_routes import dispatch_meta_and_forward as _dispatch_meta_and_forward
from .dispatch_metric_routes import dispatch_tls_and_forward as _dispatch_tls_and_forward
from .dispatch_metric_routes import dispatch_dns_and_forward as _dispatch_dns_and_forward
from .dispatch_metric_routes import dispatch_slo_and_forward as _dispatch_slo_and_forward
from .dispatch_metric_routes import dispatch_red_and_forward as _dispatch_red_and_forward
from .dispatch_probe_routes import dispatch_synthetic_and_forward as _dispatch_synthetic_and_forward
from .dispatch_probe_routes import dispatch_web_vitals_and_forward as _dispatch_web_vitals_and_forward
from .dispatch_probe_routes import dispatch_container_health_and_forward as _dispatch_container_health_and_forward
from .dispatch_probe_routes import dispatch_proxy_and_forward as _dispatch_proxy_and_forward
from .dispatch_workflow import dispatch_prompt_and_forward as _dispatch_prompt_and_forward
from .dispatch_state import (
    dispatch_state_reenable_if_due as _dispatch_state_reenable_if_due,
    dispatch_is_enabled as _dispatch_is_enabled,
    dispatch_disable as _dispatch_disable,
    dispatch_should_notify as _dispatch_should_notify,
)
from .performance import collect_performance_violations as _collect_performance_violations
from .message_performance import (
    format_ms as _format_ms,
    build_performance_alert_message as _build_performance_alert_message,
    build_performance_dispatch_prompt as _build_performance_dispatch_prompt,
)
from .message_templates import build_dispatch_prompt as _build_dispatch_prompt
from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules
from .message_templates import build_host_health_dispatch_prompt as _build_host_health_dispatch_prompt
from .message_templates import build_meta_alert_message as _build_meta_alert_message
from .message_templates import build_meta_dispatch_prompt as _build_meta_dispatch_prompt
from .message_tls_dns import build_tls_alert_message as _build_tls_alert_message
from .message_tls_dns import build_tls_dispatch_prompt as _build_tls_dispatch_prompt
from .message_tls_dns import build_dns_alert_message as _build_dns_alert_message
from .message_tls_dns import build_dns_dispatch_prompt as _build_dns_dispatch_prompt
from .message_slo_red import build_slo_alert_message as _build_slo_alert_message
from .message_slo_red import build_slo_dispatch_prompt as _build_slo_dispatch_prompt
from .message_slo_red import build_red_alert_message as _build_red_alert_message
from .message_slo_red import build_red_dispatch_prompt as _build_red_dispatch_prompt
from .message_browser import build_synthetic_alert_message as _build_synthetic_alert_message
from .message_browser import build_synthetic_dispatch_prompt as _build_synthetic_dispatch_prompt
from .message_browser import build_web_vitals_alert_message as _build_web_vitals_alert_message
from .message_browser import build_web_vitals_dispatch_prompt as _build_web_vitals_dispatch_prompt
from .message_container import build_container_health_alert_message as _build_container_health_alert_message
from .message_container import build_container_health_dispatch_prompt as _build_container_health_dispatch_prompt
from .message_proxy import build_proxy_alert_message as _build_proxy_alert_message
from .message_proxy import build_proxy_dispatch_prompt as _build_proxy_dispatch_prompt
from .host_readings import (
    compute_cpu_used_percent as _compute_cpu_used_percent,
    disk_usage_percent as _disk_usage_percent,
    format_browser_health_hint as _format_browser_health_hint,
    read_linux_meminfo_kb as _read_linux_meminfo_kb,
    read_linux_proc_stat_cpu_total_idle as _read_linux_proc_stat_cpu_total_idle,
)
from .host_snapshot import collect_host_snapshot as _collect_host_snapshot
from .host_thresholds import (
    build_host_health_alert_message as _build_host_health_alert_message,
    collect_host_health_violations as _collect_host_health_violations,
    format_percent as _format_percent,
)
from .inventory import DomainAlertPolicy, parse_domain_alert_policy, validate_domain_inventory
from .metrics_api_contract import ApiContractCheckResult, run_api_contract_checks
from .metrics_container_health import ContainerHealthIssue, check_container_health
from .metrics_dns import DnsCheckResult, check_dns
from .metrics_nginx import (
    NginxAccessWindowStats,
    NginxUpstreamErrorEvent,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)
from .metrics_proxy import ProxyIssue, check_upstream_header_expectations
from .metrics_red import RedViolation, compute_red_violations
from .metrics_slo import SloBurnViolation, compute_slo_burn_violations
from .metrics_synthetic import SyntheticTransactionResult, run_synthetic_transactions
from .metrics_tls import TlsCertCheckResult, check_tls_certs
from .metrics_web_vitals import WebVitalsResult, measure_web_vitals
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
from .cycle_values import (
    bool_field,
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

    heartbeat_cfg = cycle_section(config, "heartbeat")
    heartbeat_enabled = bool(heartbeat_cfg.get("enabled", False))
    heartbeat_timezone = str(heartbeat_cfg.get("timezone") or "UTC")
    heartbeat_times_raw = heartbeat_cfg.get("times") or []
    heartbeat_times: list[dt_time] = []
    if heartbeat_enabled:
        if not isinstance(heartbeat_times_raw, list) or not heartbeat_times_raw:
            raise ValueError("heartbeat.times must be a non-empty list of HH:MM strings when heartbeat.enabled=true")
        heartbeat_times = [_parse_hhmm(t) for t in heartbeat_times_raw]
    tz = _load_timezone(heartbeat_timezone)
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

    host_health_cfg = cycle_section(config, "host_health")
    host_health_enabled = bool(host_health_cfg.get("enabled", False))
    host_health_down_after_failures = max(1, required_int(host_health_cfg.get("down_after_failures", 1)))
    host_health_up_after_successes = max(1, required_int(host_health_cfg.get("up_after_successes", 1)))
    host_disk_used_percent_max = _coerce_optional_float(host_health_cfg.get("disk_used_percent_max"))
    host_mem_used_percent_max = _coerce_optional_float(host_health_cfg.get("mem_used_percent_max"))
    host_swap_used_percent_max = _coerce_optional_float(host_health_cfg.get("swap_used_percent_max"))
    host_cpu_used_percent_max = _coerce_optional_float(host_health_cfg.get("cpu_used_percent_max"))
    host_load1_per_cpu_max = _coerce_optional_float(host_health_cfg.get("load1_per_cpu_max"))
    host_dispatch_on_degraded = bool(host_health_cfg.get("dispatch_on_degraded", False))
    host_notify_on_recovery = bool(host_health_cfg.get("notify_on_recovery", False))

    disk_paths_raw = host_health_cfg.get("disk_paths") or []
    if not isinstance(disk_paths_raw, list) or not disk_paths_raw:
        disk_paths_raw = ["/"]
    host_disk_paths = [str(p).strip() for p in disk_paths_raw if str(p or "").strip()]
    if not host_disk_paths:
        host_disk_paths = ["/"]

    perf_cfg = cycle_section(config, "performance")
    perf_enabled = bool(perf_cfg.get("enabled", False))
    perf_down_after_failures = max(1, required_int(perf_cfg.get("down_after_failures", 1)))
    perf_up_after_successes = max(1, required_int(perf_cfg.get("up_after_successes", 1)))
    perf_http_elapsed_ms_max = _coerce_float(perf_cfg.get("http_elapsed_ms_max", 1500.0), default=1500.0)
    perf_browser_elapsed_ms_max = _coerce_float(perf_cfg.get("browser_elapsed_ms_max", 4000.0), default=4000.0)
    perf_dispatch_on_degraded = bool(perf_cfg.get("dispatch_on_degraded", False))
    perf_notify_on_recovery = bool(perf_cfg.get("notify_on_recovery", False))
    perf_overrides = None
    overrides_raw = perf_cfg.get("per_domain_overrides")
    if isinstance(overrides_raw, dict):
        perf_overrides = overrides_raw

    history_cfg = cycle_section(config, "history")
    history_retention_days = _coerce_float(history_cfg.get("retention_days", 7.0), default=7.0)
    history_retention_days = max(1.0, float(history_retention_days))
    history_retention_seconds = history_retention_days * 86400.0

    slo_cfg = cycle_section(config, "slo")
    slo_enabled = bool(slo_cfg.get("enabled", False))
    slo_target_percent = _coerce_float(slo_cfg.get("target_percent", 99.9), default=99.9)
    slo_down_after_failures = max(1, required_int(slo_cfg.get("down_after_failures", 3)))
    slo_up_after_successes = max(1, required_int(slo_cfg.get("up_after_successes", 2)))
    slo_dispatch_on_degraded = bool(slo_cfg.get("dispatch_on_degraded", False))
    slo_notify_on_recovery = bool(slo_cfg.get("notify_on_recovery", False))
    slo_min_total_samples = max(1, required_int(slo_cfg.get("min_total_samples", 5)))
    slo_rules = slo_cfg.get("burn_rate_rules")
    if not isinstance(slo_rules, list) or not slo_rules:
        slo_rules = [
            {
                "name": "page_fast_burn",
                "short_window_minutes": 5,
                "long_window_minutes": 60,
                "short_burn_rate": 14.4,
                "long_burn_rate": 6.0,
            },
            {
                "name": "ticket_slow_burn",
                "short_window_minutes": 360,
                "long_window_minutes": 4320,  # 3 days
                "short_burn_rate": 6.0,
                "long_burn_rate": 1.0,
            },
        ]

    tls_cfg = cycle_section(config, "tls")
    tls_enabled = bool(tls_cfg.get("enabled", False))
    tls_interval_minutes = max(1, required_int(tls_cfg.get("interval_minutes", 60)))
    tls_min_days_valid = _coerce_float(tls_cfg.get("min_days_valid", 14.0), default=14.0)
    tls_timeout_seconds = _coerce_float(tls_cfg.get("timeout_seconds", 8.0), default=8.0)
    tls_down_after_failures = max(1, required_int(tls_cfg.get("down_after_failures", 2)))
    tls_up_after_successes = max(1, required_int(tls_cfg.get("up_after_successes", 1)))
    tls_dispatch_on_degraded = bool(tls_cfg.get("dispatch_on_degraded", False))
    tls_notify_on_recovery = bool(tls_cfg.get("notify_on_recovery", False))

    dns_cfg = cycle_section(config, "dns")
    dns_enabled = bool(dns_cfg.get("enabled", False))
    dns_interval_minutes = max(1, required_int(dns_cfg.get("interval_minutes", 15)))
    dns_timeout_seconds = _coerce_float(dns_cfg.get("timeout_seconds", 4.0), default=4.0)
    dns_resolvers_raw = dns_cfg.get("resolvers")
    dns_resolvers = [str(x).strip() for x in dns_resolvers_raw] if isinstance(dns_resolvers_raw, list) else None
    if dns_resolvers is not None:
        dns_resolvers = [x for x in dns_resolvers if x]
        if not dns_resolvers:
            dns_resolvers = None
    dns_require_ipv4 = bool(dns_cfg.get("require_ipv4", True))
    dns_require_ipv6 = bool(dns_cfg.get("require_ipv6", False))
    dns_alert_on_drift_default = bool(dns_cfg.get("alert_on_drift", False))
    dns_expected_ips_by_domain = dns_cfg.get("expected_ips_by_domain") if isinstance(dns_cfg.get("expected_ips_by_domain"), dict) else {}
    dns_alert_on_drift_by_domain = dns_cfg.get("alert_on_drift_by_domain") if isinstance(dns_cfg.get("alert_on_drift_by_domain"), dict) else {}
    dns_down_after_failures = max(1, required_int(dns_cfg.get("down_after_failures", 2)))
    dns_up_after_successes = max(1, required_int(dns_cfg.get("up_after_successes", 1)))
    dns_dispatch_on_degraded = bool(dns_cfg.get("dispatch_on_degraded", False))
    dns_notify_on_recovery = bool(dns_cfg.get("notify_on_recovery", False))

    red_cfg = cycle_section(config, "red")
    red_enabled = bool(red_cfg.get("enabled", False))
    red_window_minutes = max(1, required_int(red_cfg.get("window_minutes", 30)))
    red_min_samples = max(1, required_int(red_cfg.get("min_samples", 10)))
    red_error_rate_max_percent = _coerce_optional_float(red_cfg.get("error_rate_max_percent"))
    red_http_p95_ms_max = _coerce_optional_float(red_cfg.get("http_p95_ms_max"))
    red_browser_p95_ms_max = _coerce_optional_float(red_cfg.get("browser_p95_ms_max"))
    red_down_after_failures = max(1, required_int(red_cfg.get("down_after_failures", 3)))
    red_up_after_successes = max(1, required_int(red_cfg.get("up_after_successes", 2)))
    red_dispatch_on_degraded = bool(red_cfg.get("dispatch_on_degraded", False))
    red_notify_on_recovery = bool(red_cfg.get("notify_on_recovery", False))

    syn_cfg = cycle_section(config, "synthetic")
    syn_enabled = bool(syn_cfg.get("enabled", False))
    syn_interval_minutes = max(1, required_int(syn_cfg.get("interval_minutes", 15)))
    syn_max_domains_per_cycle = max(1, required_int(syn_cfg.get("max_domains_per_cycle", 1)))
    syn_timeout_seconds = _coerce_float(syn_cfg.get("timeout_seconds", 35.0), default=35.0)
    syn_down_after_failures = max(1, required_int(syn_cfg.get("down_after_failures", 2)))
    syn_up_after_successes = max(1, required_int(syn_cfg.get("up_after_successes", 2)))
    syn_dispatch_on_degraded = bool(syn_cfg.get("dispatch_on_degraded", False))
    syn_notify_on_recovery = bool(syn_cfg.get("notify_on_recovery", False))

    wv_cfg = cycle_section(config, "web_vitals")
    wv_enabled = bool(wv_cfg.get("enabled", False))
    wv_interval_minutes = max(1, required_int(wv_cfg.get("interval_minutes", 60)))
    wv_max_domains_per_cycle = max(1, required_int(wv_cfg.get("max_domains_per_cycle", 1)))
    wv_timeout_seconds = _coerce_float(wv_cfg.get("timeout_seconds", 45.0), default=45.0)
    wv_post_load_wait_ms = _coerce_int(wv_cfg.get("post_load_wait_ms", 4500), default=4500)
    wv_lcp_ms_max = _coerce_optional_float(wv_cfg.get("lcp_ms_max"))
    wv_cls_max = _coerce_optional_float(wv_cfg.get("cls_max"))
    wv_inp_ms_max = _coerce_optional_float(wv_cfg.get("inp_ms_max"))
    wv_down_after_failures = max(1, required_int(wv_cfg.get("down_after_failures", 2)))
    wv_up_after_successes = max(1, required_int(wv_cfg.get("up_after_successes", 2)))
    wv_dispatch_on_degraded = bool(wv_cfg.get("dispatch_on_degraded", False))
    wv_notify_on_recovery = bool(wv_cfg.get("notify_on_recovery", False))

    api_cfg = cycle_section(config, "api_contract")
    api_enabled = bool(api_cfg.get("enabled", False))
    api_interval_minutes = max(1, required_int(api_cfg.get("interval_minutes", 10)))
    api_timeout_seconds = _coerce_float(api_cfg.get("timeout_seconds", 10.0), default=10.0)
    api_down_after_failures = max(1, required_int(api_cfg.get("down_after_failures", 2)))
    api_up_after_successes = max(1, required_int(api_cfg.get("up_after_successes", 2)))
    api_dispatch_on_degraded = bool(api_cfg.get("dispatch_on_degraded", False))
    api_notify_on_recovery = bool(api_cfg.get("notify_on_recovery", False))

    container_cfg = cycle_section(config, "container_health")
    container_enabled = bool(container_cfg.get("enabled", False))
    container_interval_minutes = max(1, required_int(container_cfg.get("interval_minutes", 1)))
    docker_socket_path = str(container_cfg.get("docker_socket_path") or "/var/run/docker.sock").strip()
    container_monitor_all = bool(container_cfg.get("monitor_all", False))
    container_include_patterns = container_cfg.get("include_name_patterns") if isinstance(container_cfg.get("include_name_patterns"), list) else []
    container_exclude_patterns = container_cfg.get("exclude_name_patterns") if isinstance(container_cfg.get("exclude_name_patterns"), list) else []
    container_timeout_seconds = _coerce_float(container_cfg.get("timeout_seconds", 3.0), default=3.0)
    container_down_after_failures = max(1, required_int(container_cfg.get("down_after_failures", 2)))
    container_up_after_successes = max(1, required_int(container_cfg.get("up_after_successes", 1)))
    container_dispatch_on_degraded = bool(container_cfg.get("dispatch_on_degraded", False))
    container_notify_on_recovery = bool(container_cfg.get("notify_on_recovery", False))

    proxy_cfg = cycle_section(config, "proxy")
    proxy_enabled = bool(proxy_cfg.get("enabled", False))
    proxy_access_log_path = str(proxy_cfg.get("access_log_path") or "/var/log/nginx/access.log").strip()
    proxy_error_log_path = str(proxy_cfg.get("error_log_path") or "/var/log/nginx/error.log").strip()
    proxy_timezone_name = str(proxy_cfg.get("timezone") or "Europe/Amsterdam").strip() or "Europe/Amsterdam"
    proxy_window_seconds = max(60, required_int(proxy_cfg.get("window_seconds", 300)))
    proxy_access_max_bytes = max(10_000, required_int(proxy_cfg.get("access_log_max_bytes", 1_000_000)))
    proxy_error_max_bytes = max(10_000, required_int(proxy_cfg.get("error_log_max_bytes", 1_000_000)))
    proxy_min_total_requests = max(0, required_int(proxy_cfg.get("min_total_requests", 50)))
    proxy_max_502_504_percent = _coerce_optional_float(proxy_cfg.get("max_502_504_percent"))
    proxy_max_upstream_errors_per_domain = max(0, required_int(proxy_cfg.get("max_upstream_errors_per_domain", 5)))
    proxy_down_after_failures = max(1, required_int(proxy_cfg.get("down_after_failures", 2)))
    proxy_up_after_successes = max(1, required_int(proxy_cfg.get("up_after_successes", 2)))
    proxy_dispatch_on_degraded = bool(proxy_cfg.get("dispatch_on_degraded", False))
    proxy_notify_on_recovery = bool(proxy_cfg.get("notify_on_recovery", False))

    meta_cfg = cycle_section(config, "meta_monitoring")
    meta_enabled = bool(meta_cfg.get("enabled", False))
    meta_cycle_overrun_factor = _coerce_float(meta_cfg.get("cycle_overrun_factor", 1.25), default=1.25)
    meta_state_write_failures_max = max(1, required_int(meta_cfg.get("state_write_failures_max", 3)))
    meta_down_after_failures = max(1, required_int(meta_cfg.get("down_after_failures", 2)))
    meta_up_after_successes = max(1, required_int(meta_cfg.get("up_after_successes", 2)))
    meta_dispatch_on_degraded = bool(meta_cfg.get("dispatch_on_degraded", False))
    meta_notify_on_recovery = bool(meta_cfg.get("notify_on_recovery", False))

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
    host_health_last_ok = True
    host_health_fail_streak = 0
    host_health_success_streak = 0
    host_cpu_prev_total = 0
    host_cpu_prev_idle = 0
    perf_last_ok = True
    perf_fail_streak = 0
    perf_success_streak = 0
    slo_last_ok = True
    slo_fail_streak = 0
    slo_success_streak = 0
    tls_last_ok = True
    tls_fail_streak = 0
    tls_success_streak = 0
    tls_last_run_ts = 0.0
    dns_last_ok = True
    dns_fail_streak = 0
    dns_success_streak = 0
    dns_last_run_ts = 0.0
    dns_last_ips: dict[str, list[str]] = {}
    red_last_ok = True
    red_fail_streak = 0
    red_success_streak = 0
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
    container_last_ok = True
    container_fail_streak = 0
    container_success_streak = 0
    container_last_run_ts = 0.0
    container_restart_counts: dict[str, int] = {}
    proxy_last_ok = True
    proxy_fail_streak = 0
    proxy_success_streak = 0
    meta_last_ok = True
    meta_fail_streak = 0
    meta_success_streak = 0
    state_write_fail_streak = 0
    signal_history: dict[str, list[list[Any]]] = {}
    dispatch_history: list[dict[str, Any]] = []
    dispatch_last: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    host_last_snapshot: dict[str, Any] = {}
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
        host_last_snapshot = disk_state.get("host_last_snapshot") if isinstance(disk_state.get("host_last_snapshot"), dict) else {}
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
                migrated: dict[str, list[list[Any]]] = {}
                for domain, items in history_by_domain.items():
                    if not isinstance(domain, str) or not domain:
                        continue
                    if not isinstance(items, list) or not items:
                        continue
                    prev_effective = True
                    f_streak = 0
                    s_streak = 0
                    out_items: list[list[Any]] = []
                    for s in items:
                        if not isinstance(s, list) or len(s) < 2:
                            continue
                        observed_ok = bool(s[1])
                        next_effective, f_streak, s_streak, _alerted = _update_effective_ok(
                            prev_effective_ok=bool(prev_effective),
                            observed_ok=observed_ok,
                            fail_streak=int(f_streak),
                            success_streak=int(s_streak),
                            down_after_failures=down_after_failures,
                            up_after_successes=up_after_successes,
                        )
                        s2 = list(s)
                        s2[1] = bool(next_effective)
                        out_items.append(s2)
                        prev_effective = bool(next_effective)
                    if out_items:
                        migrated[domain] = out_items
                history_by_domain = migrated
                LOGGER.info(
                    "Migrated history ok mode to effective prev_mode=%s domains=%s",
                    (history_ok_mode or "unknown"),
                    len(history_by_domain),
                )
            except Exception:
                LOGGER.exception("Failed to migrate history ok mode to effective")
        host_state = disk_state.get("host_health")
        if isinstance(host_state, dict):
            host_health_last_ok = bool_field(host_state, "last_ok", default=True)
            host_health_fail_streak = _coerce_int(host_state.get("fail_streak"), default=0)
            host_health_success_streak = _coerce_int(host_state.get("success_streak"), default=0)
            host_cpu_prev_total = _coerce_int(host_state.get("cpu_prev_total"), default=0)
            host_cpu_prev_idle = _coerce_int(host_state.get("cpu_prev_idle"), default=0)
        perf_state = disk_state.get("performance")
        if isinstance(perf_state, dict):
            perf_last_ok = bool_field(perf_state, "last_ok", default=True)
            perf_fail_streak = _coerce_int(perf_state.get("fail_streak"), default=0)
            perf_success_streak = _coerce_int(perf_state.get("success_streak"), default=0)
        slo_state = disk_state.get("slo")
        if isinstance(slo_state, dict):
            slo_last_ok = bool_field(slo_state, "last_ok", default=True)
            slo_fail_streak = _coerce_int(slo_state.get("fail_streak"), default=0)
            slo_success_streak = _coerce_int(slo_state.get("success_streak"), default=0)

        tls_state = disk_state.get("tls")
        if isinstance(tls_state, dict):
            tls_last_ok = bool_field(tls_state, "last_ok", default=True)
            tls_fail_streak = _coerce_int(tls_state.get("fail_streak"), default=0)
            tls_success_streak = _coerce_int(tls_state.get("success_streak"), default=0)
            tls_last_run_ts = _coerce_float(tls_state.get("last_run_ts"), default=0.0)

        dns_state = disk_state.get("dns")
        if isinstance(dns_state, dict):
            dns_last_ok = bool_field(dns_state, "last_ok", default=True)
            dns_fail_streak = _coerce_int(dns_state.get("fail_streak"), default=0)
            dns_success_streak = _coerce_int(dns_state.get("success_streak"), default=0)
            dns_last_run_ts = _coerce_float(dns_state.get("last_run_ts"), default=0.0)
            dns_last_ips = _coerce_str_list_dict(dns_state.get("last_ips"))

        red_state = disk_state.get("red")
        if isinstance(red_state, dict):
            red_last_ok = bool_field(red_state, "last_ok", default=True)
            red_fail_streak = _coerce_int(red_state.get("fail_streak"), default=0)
            red_success_streak = _coerce_int(red_state.get("success_streak"), default=0)

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
            container_last_ok = bool_field(cont_state, "last_ok", default=True)
            container_fail_streak = _coerce_int(cont_state.get("fail_streak"), default=0)
            container_success_streak = _coerce_int(cont_state.get("success_streak"), default=0)
            container_last_run_ts = _coerce_float(cont_state.get("last_run_ts"), default=0.0)
            container_restart_counts = _coerce_int_dict(cont_state.get("restart_counts"))

        proxy_state = disk_state.get("proxy")
        if isinstance(proxy_state, dict):
            proxy_last_ok = bool_field(proxy_state, "last_ok", default=True)
            proxy_fail_streak = _coerce_int(proxy_state.get("fail_streak"), default=0)
            proxy_success_streak = _coerce_int(proxy_state.get("success_streak"), default=0)

        meta_state = disk_state.get("meta")
        if isinstance(meta_state, dict):
            meta_last_ok = bool_field(meta_state, "last_ok", default=True)
            meta_fail_streak = _coerce_int(meta_state.get("fail_streak"), default=0)
            meta_success_streak = _coerce_int(meta_state.get("success_streak"), default=0)
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

    def _append_signal_sample(name: str, sample: list[Any]) -> None:
        key = str(name or "").strip()
        if not key:
            return
        if not sample:
            return
        items = signal_history.get(key)
        if items is None:
            signal_history[key] = [sample]
            return
        items.append(sample)

    def _prune_signal_history(*, before_ts: float) -> None:
        cutoff = float(before_ts)
        for key in list(signal_history.keys()):
            items = signal_history.get(key) or []
            if not items:
                signal_history.pop(key, None)
                continue
            idx = 0
            for i, s in enumerate(items):
                try:
                    ts = float(s[0])
                except Exception:
                    idx = i + 1
                    continue
                if ts >= cutoff:
                    idx = i
                    break
            else:
                idx = len(items)
            if idx <= 0:
                continue
            if idx >= len(items):
                signal_history.pop(key, None)
                continue
            del items[:idx]
            signal_history[key] = items

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
            "host_last_snapshot": host_last_snapshot,
            "browser_degraded_active": bool(monitor_state.get("browser_degraded_active", False)),
            "browser_degraded_first_seen_ts": float(monitor_state.get("browser_degraded_first_seen_ts") or 0.0),
            "browser_launch_last_error": (
                str(monitor_state.get("browser_launch_last_error"))[:800]
                if isinstance(monitor_state.get("browser_launch_last_error"), str)
                else None
            ),
            "browser_degraded_last_notice_ts": float(monitor_state.get("browser_degraded_last_notice_ts") or 0.0),
            "host_health": {
                "last_ok": bool(host_health_last_ok),
                "fail_streak": int(host_health_fail_streak),
                "success_streak": int(host_health_success_streak),
                "cpu_prev_total": int(host_cpu_prev_total),
                "cpu_prev_idle": int(host_cpu_prev_idle),
            },
            "performance": {
                "last_ok": bool(perf_last_ok),
                "fail_streak": int(perf_fail_streak),
                "success_streak": int(perf_success_streak),
            },
            "slo": {
                "last_ok": bool(slo_last_ok),
                "fail_streak": int(slo_fail_streak),
                "success_streak": int(slo_success_streak),
            },
            "tls": {
                "last_ok": bool(tls_last_ok),
                "fail_streak": int(tls_fail_streak),
                "success_streak": int(tls_success_streak),
                "last_run_ts": float(tls_last_run_ts),
            },
            "dns": {
                "last_ok": bool(dns_last_ok),
                "fail_streak": int(dns_fail_streak),
                "success_streak": int(dns_success_streak),
                "last_run_ts": float(dns_last_run_ts),
                "last_ips": dns_last_ips,
            },
            "red": {
                "last_ok": bool(red_last_ok),
                "fail_streak": int(red_fail_streak),
                "success_streak": int(red_success_streak),
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
                "last_ok": bool(container_last_ok),
                "fail_streak": int(container_fail_streak),
                "success_streak": int(container_success_streak),
                "last_run_ts": float(container_last_run_ts),
                "restart_counts": container_restart_counts,
            },
            "proxy": {
                "last_ok": bool(proxy_last_ok),
                "fail_streak": int(proxy_fail_streak),
                "success_streak": int(proxy_success_streak),
            },
            "meta": {
                "last_ok": bool(meta_last_ok),
                "fail_streak": int(meta_fail_streak),
                "success_streak": int(meta_success_streak),
                "state_write_fail_streak": int(state_write_fail_streak),
            },
        }

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
            browser: Browser | None = None

            async def _launch_browser() -> Browser:
                shm_bytes = 0
                try:
                    st = os.statvfs("/dev/shm")
                    shm_bytes = int(st.f_frsize) * int(st.f_blocks)
                except Exception:
                    shm_bytes = 0
                return await p.chromium.launch(**launch_options(shm_bytes, chromium_path))

            async def _ensure_browser(now_ts: float) -> Browser | None:
                nonlocal browser

                if browser is not None:
                    try:
                        if browser.is_connected():
                            return browser
                    except Exception:
                        pass
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    browser = None

                next_try = float(monitor_state.get("browser_launch_next_try_ts") or 0.0)
                if next_try > 0.0 and now_ts < next_try:
                    return None

                min_mem_mb = int(monitor_state.get("browser_min_mem_available_mb") or 0)
                if min_mem_mb > 0:
                    meminfo = _read_linux_meminfo_kb()
                    avail_kb = meminfo.get("MemAvailable")
                    if isinstance(avail_kb, int):
                        avail_mb = int(avail_kb / 1024)
                        if avail_mb < min_mem_mb:
                            monitor_state["browser_launch_last_error"] = (
                                f"low_mem_available_mb={avail_mb} < {min_mem_mb}"
                            )
                            monitor_state["browser_launch_next_try_ts"] = now_ts + 60.0
                            browser = None
                            return None

                try:
                    browser = await _launch_browser()
                    monitor_state["browser_launch_fail_count"] = 0
                    monitor_state["browser_launch_next_try_ts"] = 0.0
                    monitor_state["browser_launch_last_error"] = None
                    return browser
                except Exception as exc:
                    fail_count = int(monitor_state.get("browser_launch_fail_count") or 0) + 1
                    monitor_state["browser_launch_fail_count"] = fail_count
                    backoff = min(300.0, 5.0 * (2 ** min(fail_count, 6)))
                    monitor_state["browser_launch_next_try_ts"] = now_ts + backoff
                    monitor_state["browser_launch_last_error"] = f"{type(exc).__name__}: {exc}"
                    browser = None
                    LOGGER.warning(
                        "Playwright launch failed; continuing HTTP-only retry_in=%ss error=%s",
                        int(round(backoff)),
                        monitor_state["browser_launch_last_error"],
                    )
                    return None

            await _ensure_browser(time.time())
            try:
                while True:
                    cycle_started = time.time()
                    cycle_results: dict[str, DomainCheckResult] = {}
                    LOGGER.info("Running check cycle")

                    browser_degraded = False
                    # Ensure the browser is alive at the start of each cycle. This prevents a single
                    # between-cycle crash/close event from degrading *every* domain in the next cycle.
                    await _ensure_browser(time.time())

                    async def _safe_check(spec: DomainCheckSpec) -> DomainCheckResult:
                        async with check_semaphore:
                            try:
                                return await check_one_domain(
                                    spec,
                                    http_client,
                                    browser,
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

                    for domain, result in cycle_results.items():
                        details = result.details or {}
                        http_ms = None
                        try:
                            if details.get("http_elapsed_ms") is not None:
                                http_ms = float(details.get("http_elapsed_ms"))
                        except Exception:
                            http_ms = None
                        browser_ms = None
                        try:
                            if details.get("browser_elapsed_ms") is not None:
                                browser_ms = float(details.get("browser_elapsed_ms"))
                        except Exception:
                            browser_ms = None
                        status_code = None
                        try:
                            if details.get("status_code") is not None:
                                status_code = int(details.get("status_code"))
                        except Exception:
                            status_code = None

                        # IMPORTANT: use the debounced effective state for history-driven SLO/RED metrics.
                        #
                        # Rationale: a single transient failure (e.g. one Playwright timeout) is often a
                        # monitor flake and is intentionally suppressed by `down_after_failures`.
                        # Using the effective state keeps SLO burn-rate alerts aligned with our
                        # "domain is DOWN" definition, reducing false-positive budget burn.
                        effective_ok = bool(last_ok.get(domain, bool(result.ok)))

                        append_sample(
                            history_by_domain,
                            domain=domain,
                            ts=float(cycle_started),
                            ok=effective_ok,
                            http_elapsed_ms=http_ms,
                            browser_elapsed_ms=browser_ms,
                            status_code=status_code,
                        )

                    try:
                        prune_history(
                            history_by_domain,
                            before_ts=time.time() - float(history_retention_seconds),
                        )
                    except Exception:
                        LOGGER.exception("Failed to prune history")

                    # ------------------------------
                    # SLO burn-rate monitoring
                    # ------------------------------
                    slo_violations: list[SloBurnViolation] = []
                    if slo_enabled and isinstance(history_by_domain, dict) and history_by_domain:
                        try:
                            slo_violations = compute_slo_burn_violations(
                                history_by_domain=history_by_domain,
                                now_ts=time.time(),
                                slo_target_percent=float(slo_target_percent),
                                burn_rate_rules=slo_rules,
                                min_total_samples=int(slo_min_total_samples),
                            )
                        except Exception:
                            LOGGER.exception("SLO burn computation failed")
                            slo_violations = []

                        suppressed_slo_domains = sorted(
                            {v.domain for v in slo_violations if v.domain not in alertable_domains}
                        )
                        if suppressed_slo_domains:
                            LOGGER.info(
                                "SLO violations retained in domain history but excluded from Telegram routing domains=%s",
                                suppressed_slo_domains,
                            )
                        slo_violations = [v for v in slo_violations if v.domain in alertable_domains]

                        slo_observed_ok = not bool(slo_violations)
                        prev_effective = bool(slo_last_ok)
                        slo_last_ok, slo_fail_streak, slo_success_streak, slo_alerted_down = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=slo_observed_ok,
                            fail_streak=int(slo_fail_streak),
                            success_streak=int(slo_success_streak),
                            down_after_failures=slo_down_after_failures,
                            up_after_successes=slo_up_after_successes,
                        )
                        _append_signal_sample(
                            "slo",
                            [float(cycle_started), 1 if bool(slo_last_ok) else 0, int(len(slo_violations or []))],
                        )

                        if slo_alerted_down and slo_violations:
                            _append_event(
                                "slo_degraded",
                                ts=float(cycle_started),
                                violations=int(len(slo_violations)),
                                domains=[v.domain for v in slo_violations[:20]],
                            )
                            msg = _build_slo_alert_message(
                                violations=slo_violations,
                                slo_target_percent=float(slo_target_percent),
                                down_after_failures=slo_down_after_failures,
                                fail_streak=int(slo_fail_streak),
                            )
                            ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                            LOGGER.warning(
                                "SLO burn alert sent_ok=%s telegram_last=%s violations=%s",
                                ok_all,
                                redact_telegram_response(resps[-1] if resps else {}),
                                [v.domain for v in slo_violations[:5]],
                            )

                            if slo_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                if "slo" in active_dispatch_tasks and not active_dispatch_tasks["slo"].done():
                                    LOGGER.info("Dispatch already running for SLO; skipping new dispatch")
                                else:
                                    active_dispatch_tasks["slo"] = asyncio.create_task(
                                        _dispatch_slo_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            violations=slo_violations,
                                            slo_target_percent=float(slo_target_percent),
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )

                        slo_recovered = (not prev_effective) and bool(slo_last_ok)
                        if slo_recovered:
                            _append_event("slo_recovered", ts=float(cycle_started))
                        if slo_recovered and slo_notify_on_recovery:
                            ok, resp = await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "SLO burn recovered ✅ (burn-rate violations cleared).",
                            )
                            LOGGER.info(
                                "SLO burn recovery notice sent_ok=%s telegram=%s",
                                ok,
                                redact_telegram_response(resp),
                            )

                    # ------------------------------
                    # RED / golden signals
                    # ------------------------------
                    red_violations: list[RedViolation] = []
                    if red_enabled and isinstance(history_by_domain, dict) and history_by_domain:
                        try:
                            red_violations = compute_red_violations(
                                history_by_domain=history_by_domain,
                                now_ts=time.time(),
                                window_minutes=int(red_window_minutes),
                                min_samples=int(red_min_samples),
                                error_rate_max_percent=red_error_rate_max_percent,
                                http_p95_ms_max=red_http_p95_ms_max,
                                browser_p95_ms_max=red_browser_p95_ms_max,
                            )
                        except Exception:
                            LOGGER.exception("RED computation failed")
                            red_violations = []

                        suppressed_red_domains = sorted(
                            {v.domain for v in red_violations if v.domain not in alertable_domains}
                        )
                        if suppressed_red_domains:
                            LOGGER.info(
                                "RED violations retained in domain history but excluded from Telegram routing domains=%s",
                                suppressed_red_domains,
                            )
                        red_violations = [v for v in red_violations if v.domain in alertable_domains]

                        red_observed_ok = not bool(red_violations)
                        prev_effective = bool(red_last_ok)
                        red_last_ok, red_fail_streak, red_success_streak, red_alerted_down = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=red_observed_ok,
                            fail_streak=int(red_fail_streak),
                            success_streak=int(red_success_streak),
                            down_after_failures=red_down_after_failures,
                            up_after_successes=red_up_after_successes,
                        )
                        _append_signal_sample(
                            "red",
                            [float(cycle_started), 1 if bool(red_last_ok) else 0, int(len(red_violations or []))],
                        )

                        if red_alerted_down and red_violations:
                            _append_event(
                                "red_degraded",
                                ts=float(cycle_started),
                                violations=int(len(red_violations)),
                                domains=[v.domain for v in red_violations[:20]],
                            )
                            msg = _build_red_alert_message(
                                violations=red_violations,
                                window_minutes=int(red_window_minutes),
                                down_after_failures=red_down_after_failures,
                                fail_streak=int(red_fail_streak),
                            )
                            ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                            LOGGER.warning(
                                "RED degraded alert sent_ok=%s telegram_last=%s domains=%s",
                                ok_all,
                                redact_telegram_response(resps[-1] if resps else {}),
                                [v.domain for v in red_violations[:5]],
                            )

                            if red_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                if "red" in active_dispatch_tasks and not active_dispatch_tasks["red"].done():
                                    LOGGER.info("Dispatch already running for RED; skipping new dispatch")
                                else:
                                    active_dispatch_tasks["red"] = asyncio.create_task(
                                        _dispatch_red_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            violations=red_violations,
                                            window_minutes=int(red_window_minutes),
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )

                        red_recovered = (not prev_effective) and bool(red_last_ok)
                        if red_recovered:
                            _append_event("red_recovered", ts=float(cycle_started))
                        if red_recovered and red_notify_on_recovery:
                            ok, resp = await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "RED signals recovered ✅ (error-rate/latency back under thresholds).",
                            )
                            LOGGER.info(
                                "RED recovery notice sent_ok=%s telegram=%s",
                                ok,
                                redact_telegram_response(resp),
                            )

                    host_snap: dict[str, Any] | None = None
                    host_violations: list[str] | None = None
                    if host_health_enabled:
                        host_snap = _collect_host_snapshot(
                            disk_paths=host_disk_paths,
                            cpu_prev_total=host_cpu_prev_total,
                            cpu_prev_idle=host_cpu_prev_idle,
                        )
                        host_violations = _collect_host_health_violations(
                            host_snap,
                            disk_used_percent_max=host_disk_used_percent_max,
                            mem_used_percent_max=host_mem_used_percent_max,
                            swap_used_percent_max=host_swap_used_percent_max,
                            cpu_used_percent_max=host_cpu_used_percent_max,
                            load1_per_cpu_max=host_load1_per_cpu_max,
                        )

                        cpu_prev_total_next = host_snap.get("cpu_prev_total_next")
                        cpu_prev_idle_next = host_snap.get("cpu_prev_idle_next")
                        if cpu_prev_total_next is not None and cpu_prev_idle_next is not None:
                            try:
                                host_cpu_prev_total = int(cpu_prev_total_next)
                                host_cpu_prev_idle = int(cpu_prev_idle_next)
                            except Exception:
                                pass

                        host_observed_ok = not bool(host_violations)
                        prev_effective = bool(host_health_last_ok)
                        (
                            host_health_last_ok,
                            host_health_fail_streak,
                            host_health_success_streak,
                            host_alerted_down,
                        ) = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=host_observed_ok,
                            fail_streak=int(host_health_fail_streak),
                            success_streak=int(host_health_success_streak),
                            down_after_failures=host_health_down_after_failures,
                            up_after_successes=host_health_up_after_successes,
                        )

                        # Persist last host snapshot for dashboard visibility (and time-series history below).
                        try:
                            host_last_snapshot = dict(host_snap)
                            host_last_snapshot.pop("cpu_prev_total_next", None)
                            host_last_snapshot.pop("cpu_prev_idle_next", None)
                        except Exception:
                            host_last_snapshot = host_snap or {}

                        disk_worst_used_percent = None
                        disk = host_snap.get("disk") if isinstance(host_snap.get("disk"), dict) else {}
                        for _path, info in disk.items():
                            if not isinstance(info, dict):
                                continue
                            pct = info.get("used_percent")
                            try:
                                pct_f = float(pct)
                            except Exception:
                                continue
                            if disk_worst_used_percent is None or pct_f > disk_worst_used_percent:
                                disk_worst_used_percent = pct_f

                        _append_signal_sample(
                            "host_health",
                            [
                                float(cycle_started),
                                1 if bool(host_health_last_ok) else 0,
                                host_snap.get("mem_used_percent"),
                                host_snap.get("swap_used_percent"),
                                host_snap.get("cpu_used_percent"),
                                host_snap.get("load1_per_cpu"),
                                disk_worst_used_percent,
                                int(len(host_violations or [])),
                            ],
                        )

                        if host_alerted_down and host_violations:
                            _append_event("host_health_degraded", ts=float(cycle_started), violations=host_violations[:20])
                            msg = _build_host_health_alert_message(
                                violations=host_violations,
                                snap=host_snap,
                                down_after_failures=host_health_down_after_failures,
                                fail_streak=int(host_health_fail_streak),
                            )
                            ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                            LOGGER.warning(
                                "Host health degraded alert sent_ok=%s telegram_last=%s violations=%s",
                                ok_all,
                                redact_telegram_response(resps[-1] if resps else {}),
                                host_violations[:5],
                            )

                            if (
                                host_dispatch_on_degraded
                                and dispatch_cfg
                                and _dispatch_is_enabled(dispatch_cfg, dispatch_state)
                            ):
                                if "host_health" in active_dispatch_tasks and not active_dispatch_tasks[
                                    "host_health"
                                ].done():
                                    LOGGER.info(
                                        "Dispatch already running for host_health; skipping new dispatch"
                                    )
                                else:
                                    active_dispatch_tasks["host_health"] = asyncio.create_task(
                                        _dispatch_host_health_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            violations=host_violations,
                                            snap=host_snap,
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )

                        host_recovered = (not prev_effective) and bool(host_health_last_ok)
                        if host_recovered:
                            _append_event("host_health_recovered", ts=float(cycle_started))
                        if host_recovered and host_notify_on_recovery:
                            ok, resp = await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "Host health recovered ✅ (threshold violations cleared).",
                            )
                            LOGGER.info(
                                "Host health recovery notice sent_ok=%s telegram=%s",
                                ok,
                                redact_telegram_response(resp),
                            )

                    perf_slow: list[dict[str, Any]] | None = None
                    if perf_enabled and cycle_results:
                        perf_slow = _collect_performance_violations(
                            cycle_results,
                            http_elapsed_ms_max=perf_http_elapsed_ms_max,
                            browser_elapsed_ms_max=perf_browser_elapsed_ms_max,
                            per_domain_overrides=perf_overrides,
                        )
                        suppressed_perf_domains = sorted(
                            {
                                str(item.get("domain"))
                                for item in perf_slow
                                if str(item.get("domain")) not in alertable_domains
                            }
                        )
                        if suppressed_perf_domains:
                            LOGGER.info(
                                "Performance violations retained in domain history but excluded from Telegram routing domains=%s",
                                suppressed_perf_domains,
                            )
                        perf_slow = [
                            item for item in perf_slow if str(item.get("domain")) in alertable_domains
                        ]
                        perf_observed_ok = not bool(perf_slow)
                        prev_effective = bool(perf_last_ok)
                        perf_last_ok, perf_fail_streak, perf_success_streak, perf_alerted_down = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=perf_observed_ok,
                            fail_streak=int(perf_fail_streak),
                            success_streak=int(perf_success_streak),
                            down_after_failures=perf_down_after_failures,
                            up_after_successes=perf_up_after_successes,
                        )
                        _append_signal_sample(
                            "performance",
                            [float(cycle_started), 1 if bool(perf_last_ok) else 0, int(len(perf_slow or []))],
                        )

                        if perf_alerted_down and perf_slow:
                            _append_event(
                                "performance_degraded",
                                ts=float(cycle_started),
                                slow_domains=[e.get("domain") for e in perf_slow[:20]],
                            )
                            msg = _build_performance_alert_message(
                                slow=perf_slow,
                                down_after_failures=perf_down_after_failures,
                                fail_streak=int(perf_fail_streak),
                            )
                            ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                            LOGGER.warning(
                                "Performance degraded alert sent_ok=%s telegram_last=%s slow_domains=%s",
                                ok_all,
                                redact_telegram_response(resps[-1] if resps else {}),
                                [e.get("domain") for e in perf_slow[:5]],
                            )

                            if (
                                perf_dispatch_on_degraded
                                and dispatch_cfg
                                and _dispatch_is_enabled(dispatch_cfg, dispatch_state)
                            ):
                                if "performance" in active_dispatch_tasks and not active_dispatch_tasks[
                                    "performance"
                                ].done():
                                    LOGGER.info(
                                        "Dispatch already running for performance; skipping new dispatch"
                                    )
                                else:
                                    active_dispatch_tasks["performance"] = asyncio.create_task(
                                        _dispatch_performance_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            slow=perf_slow,
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )

                        perf_recovered = (not prev_effective) and bool(perf_last_ok)
                        if perf_recovered:
                            _append_event("performance_recovered", ts=float(cycle_started))
                        if perf_recovered and perf_notify_on_recovery:
                            ok, resp = await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "Performance recovered ✅ (response times back under thresholds).",
                            )
                            LOGGER.info(
                                "Performance recovery notice sent_ok=%s telegram=%s",
                                ok,
                                redact_telegram_response(resp),
                            )

                    # ------------------------------
                    # TLS certificate checks (expiry / handshake)
                    # ------------------------------
                    tls_results: list[TlsCertCheckResult] | None = None
                    if tls_enabled:
                        now_ts = time.time()
                        due = (now_ts - float(tls_last_run_ts or 0.0)) >= float(tls_interval_minutes * 60)
                        if due and enabled_specs:
                            tls_last_run_ts = now_ts
                            urls_by_domain = {s.domain: s.url for s in enabled_specs}
                            try:
                                tls_results = await check_tls_certs(
                                    urls_by_domain=urls_by_domain,
                                    min_days_valid=float(tls_min_days_valid),
                                    timeout_seconds=float(tls_timeout_seconds),
                                    concurrency=min(50, max(5, len(urls_by_domain))),
                                )
                            except Exception:
                                LOGGER.exception("TLS cert checks crashed")
                                tls_results = [
                                    TlsCertCheckResult(
                                        domain="tls",
                                        ok=False,
                                        host=None,
                                        port=None,
                                        not_after_iso=None,
                                        days_remaining=None,
                                        error="tls_check_crashed",
                                        details={},
                                    )
                                ]

                            suppressed_tls_domains = sorted(
                                {
                                    r.domain
                                    for r in (tls_results or [])
                                    if not r.ok and r.domain in entries_by_domain and r.domain not in alertable_domains
                                }
                            )
                            if suppressed_tls_domains:
                                LOGGER.info(
                                    "TLS failures excluded from Telegram routing domains=%s",
                                    suppressed_tls_domains,
                                )
                            tls_alert_results = [
                                r
                                for r in (tls_results or [])
                                if r.domain not in entries_by_domain or r.domain in alertable_domains
                            ]
                            tls_observed_ok = all(r.ok for r in tls_alert_results)
                            prev_effective = bool(tls_last_ok)
                            tls_last_ok, tls_fail_streak, tls_success_streak, tls_alerted_down = _update_effective_ok(
                                prev_effective_ok=prev_effective,
                                observed_ok=tls_observed_ok,
                                fail_streak=int(tls_fail_streak),
                                success_streak=int(tls_success_streak),
                                down_after_failures=tls_down_after_failures,
                                up_after_successes=tls_up_after_successes,
                            )
                            tls_fail_count = 0
                            try:
                                tls_fail_count = sum(
                                    1 for r in tls_alert_results if not bool(getattr(r, "ok", False))
                                )
                            except Exception:
                                tls_fail_count = 0
                            _append_signal_sample(
                                "tls",
                                [float(cycle_started), 1 if bool(tls_last_ok) else 0, int(tls_fail_count)],
                            )

                            if tls_alerted_down and tls_alert_results and (not tls_observed_ok):
                                _append_event(
                                    "tls_degraded",
                                    ts=float(cycle_started),
                                    failures=int(tls_fail_count),
                                    domains=[r.domain for r in tls_alert_results if not r.ok][:20],
                                )
                                msg = _build_tls_alert_message(
                                    results=tls_alert_results,
                                    min_days_valid=float(tls_min_days_valid),
                                    down_after_failures=tls_down_after_failures,
                                    fail_streak=int(tls_fail_streak),
                                )
                                ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                                LOGGER.warning(
                                    "TLS degraded alert sent_ok=%s telegram_last=%s",
                                    ok_all,
                                    redact_telegram_response(resps[-1] if resps else {}),
                                )

                                if tls_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                    if "tls" in active_dispatch_tasks and not active_dispatch_tasks["tls"].done():
                                        LOGGER.info("Dispatch already running for TLS; skipping new dispatch")
                                    else:
                                        active_dispatch_tasks["tls"] = asyncio.create_task(
                                            _dispatch_tls_and_forward(
                                                http_client=http_client,
                                                telegram_cfg=telegram_cfg,
                                                dispatch_cfg=dispatch_cfg,
                                                dispatch_state=dispatch_state,
                                                results=tls_alert_results,
                                                min_days_valid=float(tls_min_days_valid),
                                                dispatch_history=dispatch_history,
                                                dispatch_last=dispatch_last,
                                                events=events,
                                            )
                                        )

                            tls_recovered = (not prev_effective) and bool(tls_last_ok)
                            if tls_recovered:
                                _append_event("tls_recovered", ts=float(cycle_started))
                            if tls_recovered and tls_notify_on_recovery:
                                ok, resp = await send_telegram_message(
                                    http_client,
                                    telegram_cfg,
                                    "TLS checks recovered ✅ (certificate issues cleared).",
                                )
                                LOGGER.info(
                                    "TLS recovery notice sent_ok=%s telegram=%s",
                                    ok,
                                    redact_telegram_response(resp),
                                )

                    # ------------------------------
                    # DNS checks (resolution / drift)
                    # ------------------------------
                    dns_results: list[DnsCheckResult] | None = None
                    if dns_enabled:
                        now_ts = time.time()
                        due = (now_ts - float(dns_last_run_ts or 0.0)) >= float(dns_interval_minutes * 60)
                        if due and enabled_specs:
                            dns_last_run_ts = now_ts
                            enabled_domains = [s.domain for s in enabled_specs]

                            # Normalize per-domain configs to lowercase keys.
                            expected_ips_norm: dict[str, list[str]] = {}
                            if isinstance(dns_expected_ips_by_domain, dict):
                                for k, v in dns_expected_ips_by_domain.items():
                                    kk = str(k or "").strip().lower()
                                    if not kk:
                                        continue
                                    expected_ips_norm[kk] = v if isinstance(v, list) else [v]

                            drift_norm: dict[str, bool] = {d.lower(): bool(dns_alert_on_drift_default) for d in enabled_domains}
                            if isinstance(dns_alert_on_drift_by_domain, dict):
                                for k, v in dns_alert_on_drift_by_domain.items():
                                    kk = str(k or "").strip().lower()
                                    if not kk:
                                        continue
                                    drift_norm[kk] = bool(v)

                            try:
                                dns_results = await check_dns(
                                    domains=enabled_domains,
                                    resolvers=dns_resolvers,
                                    timeout_seconds=float(dns_timeout_seconds),
                                    require_ipv4=bool(dns_require_ipv4),
                                    require_ipv6=bool(dns_require_ipv6),
                                    previous_ips_by_domain=dns_last_ips,
                                    expected_ips_by_domain=expected_ips_norm,
                                    alert_on_drift_by_domain=drift_norm,
                                )
                            except Exception:
                                LOGGER.exception("DNS checks crashed")
                                dns_results = [
                                    DnsCheckResult(
                                        domain="dns",
                                        ok=False,
                                        a_records=[],
                                        aaaa_records=[],
                                        error="dns_check_crashed",
                                        drift_detected=False,
                                        expected_ips=None,
                                    )
                                ]

                            # Update baseline for drift checks.
                            if dns_results:
                                for r in dns_results:
                                    cur = sorted(set((r.a_records or []) + (r.aaaa_records or [])))
                                    dns_last_ips[r.domain] = cur

                            suppressed_dns_domains = sorted(
                                {
                                    r.domain
                                    for r in (dns_results or [])
                                    if not r.ok and r.domain in entries_by_domain and r.domain not in alertable_domains
                                }
                            )
                            if suppressed_dns_domains:
                                LOGGER.info(
                                    "DNS failures excluded from Telegram routing domains=%s",
                                    suppressed_dns_domains,
                                )
                            dns_alert_results = [
                                r
                                for r in (dns_results or [])
                                if r.domain not in entries_by_domain or r.domain in alertable_domains
                            ]
                            dns_observed_ok = all(r.ok for r in dns_alert_results)
                            prev_effective = bool(dns_last_ok)
                            dns_last_ok, dns_fail_streak, dns_success_streak, dns_alerted_down = _update_effective_ok(
                                prev_effective_ok=prev_effective,
                                observed_ok=dns_observed_ok,
                                fail_streak=int(dns_fail_streak),
                                success_streak=int(dns_success_streak),
                                down_after_failures=dns_down_after_failures,
                                up_after_successes=dns_up_after_successes,
                            )
                            dns_fail_count = 0
                            try:
                                dns_fail_count = sum(
                                    1 for r in dns_alert_results if not bool(getattr(r, "ok", False))
                                )
                            except Exception:
                                dns_fail_count = 0
                            _append_signal_sample(
                                "dns",
                                [float(cycle_started), 1 if bool(dns_last_ok) else 0, int(dns_fail_count)],
                            )

                            if dns_alerted_down and dns_alert_results and (not dns_observed_ok):
                                _append_event(
                                    "dns_degraded",
                                    ts=float(cycle_started),
                                    failures=int(dns_fail_count),
                                    domains=[r.domain for r in dns_alert_results if not r.ok][:20],
                                )
                                msg = _build_dns_alert_message(
                                    results=dns_alert_results,
                                    down_after_failures=dns_down_after_failures,
                                    fail_streak=int(dns_fail_streak),
                                )
                                ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                                LOGGER.warning(
                                    "DNS degraded alert sent_ok=%s telegram_last=%s",
                                    ok_all,
                                    redact_telegram_response(resps[-1] if resps else {}),
                                )

                                if dns_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                    if "dns" in active_dispatch_tasks and not active_dispatch_tasks["dns"].done():
                                        LOGGER.info("Dispatch already running for DNS; skipping new dispatch")
                                    else:
                                        active_dispatch_tasks["dns"] = asyncio.create_task(
                                            _dispatch_dns_and_forward(
                                                http_client=http_client,
                                                telegram_cfg=telegram_cfg,
                                                dispatch_cfg=dispatch_cfg,
                                                dispatch_state=dispatch_state,
                                                results=dns_alert_results,
                                                dispatch_history=dispatch_history,
                                                dispatch_last=dispatch_last,
                                                events=events,
                                            )
                                        )

                            dns_recovered = (not prev_effective) and bool(dns_last_ok)
                            if dns_recovered:
                                _append_event("dns_recovered", ts=float(cycle_started))
                            if dns_recovered and dns_notify_on_recovery:
                                ok, resp = await send_telegram_message(
                                    http_client,
                                    telegram_cfg,
                                    "DNS checks recovered ✅ (resolution issues cleared).",
                                )
                                LOGGER.info(
                                    "DNS recovery notice sent_ok=%s telegram=%s",
                                    ok,
                                    redact_telegram_response(resp),
                                )

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
                    container_issues: list[ContainerHealthIssue] | None = None
                    if container_enabled:
                        now_ts = time.time()
                        due = (now_ts - float(container_last_run_ts or 0.0)) >= float(container_interval_minutes * 60)
                        if due:
                            container_last_run_ts = now_ts
                            try:
                                container_issues, container_restart_counts_next = await check_container_health(
                                    docker_socket_path=docker_socket_path,
                                    include_name_patterns=container_include_patterns,
                                    exclude_name_patterns=container_exclude_patterns,
                                    monitor_all=bool(container_monitor_all),
                                    previous_restart_counts=container_restart_counts,
                                    timeout_seconds=float(container_timeout_seconds),
                                )
                                container_restart_counts = container_restart_counts_next
                            except Exception:
                                LOGGER.exception("Container health check crashed")
                                container_issues = [
                                    ContainerHealthIssue(
                                        name="docker",
                                        container_id="",
                                        running=None,
                                        status=None,
                                        restart_count=None,
                                        restart_increase=None,
                                        oom_killed=None,
                                        health_status=None,
                                        exit_code=None,
                                        error="container_health_check_crashed",
                                    )
                                ]

                            container_observed_ok = not bool(container_issues)
                            prev_effective = bool(container_last_ok)
                            (
                                container_last_ok,
                                container_fail_streak,
                                container_success_streak,
                                container_alerted_down,
                            ) = _update_effective_ok(
                                prev_effective_ok=prev_effective,
                                observed_ok=container_observed_ok,
                                fail_streak=int(container_fail_streak),
                                success_streak=int(container_success_streak),
                                down_after_failures=container_down_after_failures,
                                up_after_successes=container_up_after_successes,
                            )
                            container_issue_count = int(len(container_issues or []))
                            _append_signal_sample(
                                "container_health",
                                [float(cycle_started), 1 if bool(container_last_ok) else 0, container_issue_count],
                            )

                            if container_alerted_down and container_issues:
                                _append_event(
                                    "container_health_degraded",
                                    ts=float(cycle_started),
                                    issues=[it.name for it in container_issues[:20]],
                                )
                                msg = _build_container_health_alert_message(
                                    issues=container_issues,
                                    down_after_failures=container_down_after_failures,
                                    fail_streak=int(container_fail_streak),
                                )
                                ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                                LOGGER.warning(
                                    "Container health degraded alert sent_ok=%s telegram_last=%s issues=%s",
                                    ok_all,
                                    redact_telegram_response(resps[-1] if resps else {}),
                                    [it.name for it in container_issues[:5]],
                                )

                                if container_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                    if "container_health" in active_dispatch_tasks and not active_dispatch_tasks["container_health"].done():
                                        LOGGER.info("Dispatch already running for container_health; skipping new dispatch")
                                    else:
                                        active_dispatch_tasks["container_health"] = asyncio.create_task(
                                            _dispatch_container_health_and_forward(
                                                http_client=http_client,
                                                telegram_cfg=telegram_cfg,
                                                dispatch_cfg=dispatch_cfg,
                                                dispatch_state=dispatch_state,
                                                issues=container_issues,
                                                dispatch_history=dispatch_history,
                                                dispatch_last=dispatch_last,
                                                events=events,
                                            )
                                        )

                            container_recovered = (not prev_effective) and bool(container_last_ok)
                            if container_recovered:
                                _append_event("container_health_recovered", ts=float(cycle_started))
                            if container_recovered and container_notify_on_recovery:
                                ok, resp = await send_telegram_message(
                                    http_client,
                                    telegram_cfg,
                                    "Container health recovered ✅",
                                )
                                LOGGER.info(
                                    "Container health recovery notice sent_ok=%s telegram=%s",
                                    ok,
                                    redact_telegram_response(resp),
                                )

                    # ------------------------------
                    # Reverse proxy upstream/failover checks
                    # ------------------------------
                    if proxy_enabled and cycle_results:
                        proxy_tz = _load_timezone(proxy_timezone_name)
                        all_upstream_issues = check_upstream_header_expectations(
                            specs_by_domain=specs_by_domain, cycle_results=cycle_results
                        )
                        suppressed_proxy_domains = sorted(
                            {
                                issue.domain
                                for issue in all_upstream_issues
                                if issue.domain not in alertable_domains
                            }
                        )
                        if suppressed_proxy_domains:
                            LOGGER.info(
                                "Proxy header failures excluded from Telegram routing domains=%s",
                                suppressed_proxy_domains,
                            )
                        upstream_issues = [
                            issue for issue in all_upstream_issues if issue.domain in alertable_domains
                        ]

                        access_stats = None
                        access_violation = False
                        if proxy_max_502_504_percent is not None and proxy_access_log_path:
                            access_stats = dft_cycle.read_access(
                                access_log_path=proxy_access_log_path,
                                now=datetime.now(timezone.utc),
                                window_seconds=int(proxy_window_seconds),
                                max_bytes=int(proxy_access_max_bytes),
                            )
                            if access_stats is not None and access_stats.total >= int(proxy_min_total_requests):
                                pct = (int(access_stats.status_502_504) / float(access_stats.total or 1)) * 100.0
                                if float(pct) > float(proxy_max_502_504_percent):
                                    access_violation = True

                        upstream_events = []
                        upstream_summary = None
                        upstream_violation = False
                        if proxy_error_log_path and proxy_max_upstream_errors_per_domain > 0:
                            all_upstream_events = parse_recent_upstream_errors(
                                error_log_path=proxy_error_log_path,
                                now=datetime.now(timezone.utc),
                                window_seconds=int(proxy_window_seconds),
                                local_tz=proxy_tz,
                                max_bytes=int(proxy_error_max_bytes),
                            )
                            upstream_events = [
                                event
                                for event in all_upstream_events
                                if event.server not in entries_by_domain or event.server in alertable_domains
                            ]
                            upstream_summary = summarize_upstream_errors(upstream_events)
                            counts = upstream_summary.get("counts_by_server") if isinstance(upstream_summary, dict) else {}
                            if isinstance(counts, dict):
                                enabled_domains = {
                                    s.domain for s in enabled_specs if s.domain in alertable_domains
                                }
                                for server, count in counts.items():
                                    if server not in enabled_domains:
                                        continue
                                    if int(count) >= int(proxy_max_upstream_errors_per_domain):
                                        upstream_violation = True
                                        break

                        # The access-log rate has no domain attribution in the configured
                        # Nginx combined log format, so it remains a global critical signal.
                        # Domain policy applies only where the failing domain is known.
                        proxy_observed_ok = (
                            (not upstream_issues)
                            and (not access_violation)
                            and (not upstream_violation)
                            and (dft_cycle.coverage_ok or proxy_last_ok)
                        )
                        prev_effective = bool(proxy_last_ok)
                        proxy_last_ok, proxy_fail_streak, proxy_success_streak, proxy_alerted_down = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=proxy_observed_ok,
                            fail_streak=int(proxy_fail_streak),
                            success_streak=int(proxy_success_streak),
                            down_after_failures=proxy_down_after_failures,
                            up_after_successes=proxy_up_after_successes,
                        )
                        pct_502_504 = None
                        access_total = 0
                        access_502_504 = 0
                        if access_stats is not None:
                            try:
                                access_total = int(access_stats.total)
                                access_502_504 = int(access_stats.status_502_504)
                                pct_502_504 = (access_502_504 / float(access_total or 1)) * 100.0
                            except Exception:
                                pct_502_504 = None
                                access_total = 0
                                access_502_504 = 0
                        _append_signal_sample(
                            "proxy",
                            [
                                float(cycle_started),
                                1 if bool(proxy_last_ok) else 0,
                                int(len(upstream_issues or [])),
                                pct_502_504,
                                int(access_total),
                                int(access_502_504),
                                int(len(upstream_events or [])),
                            ],
                        )

                        if proxy_alerted_down and (not proxy_observed_ok):
                            _append_event(
                                "proxy_degraded",
                                ts=float(cycle_started),
                                upstream_issues=int(len(upstream_issues or [])),
                                access_502_504_percent=pct_502_504,
                                upstream_events=int(len(upstream_events or [])),
                            )
                            msg = _build_proxy_alert_message(
                                upstream_issues=upstream_issues,
                                access_stats=access_stats,
                                upstream_errors_summary=upstream_summary,
                                window_seconds=int(proxy_window_seconds),
                                down_after_failures=proxy_down_after_failures,
                                fail_streak=int(proxy_fail_streak),
                            )
                            ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                            LOGGER.warning(
                                "Proxy degraded alert sent_ok=%s telegram_last=%s",
                                ok_all,
                                redact_telegram_response(resps[-1] if resps else {}),
                            )

                            if proxy_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                if "proxy" in active_dispatch_tasks and not active_dispatch_tasks["proxy"].done():
                                    LOGGER.info("Dispatch already running for proxy; skipping new dispatch")
                                else:
                                    active_dispatch_tasks["proxy"] = asyncio.create_task(
                                        _dispatch_proxy_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            upstream_issues=upstream_issues,
                                            access_stats=access_stats,
                                            upstream_error_events=upstream_events,
                                            window_seconds=int(proxy_window_seconds),
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )

                        proxy_recovered = (not prev_effective) and bool(proxy_last_ok)
                        if proxy_recovered:
                            _append_event("proxy_recovered", ts=float(cycle_started))
                        if proxy_recovered and proxy_notify_on_recovery:
                            ok, resp = await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "Proxy/upstream signals recovered ✅",
                            )
                            LOGGER.info(
                                "Proxy recovery notice sent_ok=%s telegram=%s",
                                ok,
                                redact_telegram_response(resp),
                            )

                    # ------------------------------
                    # Synthetic transactions (Playwright step flows)
                    # ------------------------------
                    syn_failures_for_dispatch: list[SyntheticTransactionResult] = []
                    if syn_enabled and enabled_specs and browser is not None and not browser_degraded:
                        now_ts = time.time()
                        candidates = [
                            s
                            for s in enabled_specs
                            if s.synthetic_transactions
                            and (now_ts - float(synthetic_last_run_ts.get(s.domain, 0.0))) >= float(syn_interval_minutes * 60)
                        ]
                        candidates.sort(key=lambda s: float(synthetic_last_run_ts.get(s.domain, 0.0)))
                        for spec in candidates[: int(syn_max_domains_per_cycle)]:
                            synthetic_last_run_ts[spec.domain] = now_ts
                            results = await run_synthetic_transactions(
                                domain=spec.domain,
                                base_url=spec.url,
                                browser=browser,
                                transactions=spec.synthetic_transactions,
                                timeout_seconds=float(syn_timeout_seconds),
                            )
                            real_failures = [r for r in results if (not r.ok) and (not r.browser_infra_error)]
                            observed_ok = not bool(real_failures)
                            prev_effective = synthetic_last_ok.get(spec.domain, True)
                            (
                                next_effective,
                                next_fail,
                                next_success,
                                alerted_down,
                            ) = _update_effective_ok(
                                prev_effective_ok=bool(prev_effective),
                                observed_ok=observed_ok,
                                fail_streak=int(synthetic_fail_streak.get(spec.domain, 0)),
                                success_streak=int(synthetic_success_streak.get(spec.domain, 0)),
                                down_after_failures=syn_down_after_failures,
                                up_after_successes=syn_up_after_successes,
                            )
                            synthetic_last_ok[spec.domain] = next_effective
                            synthetic_fail_streak[spec.domain] = next_fail
                            synthetic_success_streak[spec.domain] = next_success

                            if alerted_down and real_failures:
                                domain_entry = entries_by_domain[spec.domain]
                                _append_event(
                                    "synthetic_degraded",
                                    ts=float(cycle_started),
                                    domain=spec.domain,
                                    failures=int(len(real_failures)),
                                    telegram_alert=domain_entry.routes_telegram,
                                    alert_policy=domain_entry.alert_policy.telegram,
                                )
                                msg = _build_synthetic_alert_message(
                                    failures=real_failures,
                                    down_after_failures=syn_down_after_failures,
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
                                        "Synthetic degraded domain=%s sent_ok=%s telegram_last=%s",
                                        spec.domain,
                                        ok_all,
                                        redact_telegram_response(resps[-1] if resps else {}),
                                    )
                                    syn_failures_for_dispatch.extend(real_failures)
                            else:
                                recovered = (not prev_effective) and bool(next_effective)
                                if recovered:
                                    _append_event(
                                        "synthetic_recovered",
                                        ts=float(cycle_started),
                                        domain=spec.domain,
                                    )
                                if (
                                    recovered
                                    and syn_notify_on_recovery
                                    and entries_by_domain[spec.domain].routes_telegram
                                ):
                                    ok, resp = await send_telegram_message(
                                        http_client,
                                        telegram_cfg,
                                        f"Synthetic transactions recovered ✅ domain={spec.domain}",
                                    )
                                    LOGGER.info(
                                        "Synthetic recovery notice sent_ok=%s telegram=%s domain=%s",
                                        ok,
                                        redact_telegram_response(resp),
                                        spec.domain,
                                    )

                        if syn_failures_for_dispatch and syn_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                            if "synthetic" in active_dispatch_tasks and not active_dispatch_tasks["synthetic"].done():
                                LOGGER.info("Dispatch already running for synthetic; skipping new dispatch")
                            else:
                                active_dispatch_tasks["synthetic"] = asyncio.create_task(
                                    _dispatch_synthetic_and_forward(
                                        http_client=http_client,
                                        telegram_cfg=telegram_cfg,
                                        dispatch_cfg=dispatch_cfg,
                                        dispatch_state=dispatch_state,
                                        failures=syn_failures_for_dispatch,
                                        dispatch_history=dispatch_history,
                                        dispatch_last=dispatch_last,
                                        events=events,
                                    )
                                )

                    # ------------------------------
                    # Core Web Vitals (browser metrics)
                    # ------------------------------
                    wv_failures_for_dispatch: list[WebVitalsResult] = []
                    if wv_enabled and enabled_specs and browser is not None and not browser_degraded:
                        now_ts = time.time()
                        candidates = [
                            s
                            for s in enabled_specs
                            if (now_ts - float(web_vitals_last_run_ts.get(s.domain, 0.0))) >= float(wv_interval_minutes * 60)
                        ]
                        candidates.sort(key=lambda s: float(web_vitals_last_run_ts.get(s.domain, 0.0)))
                        for spec in candidates[: int(wv_max_domains_per_cycle)]:
                            web_vitals_last_run_ts[spec.domain] = now_ts
                            r = await measure_web_vitals(
                                domain=spec.domain,
                                url=spec.url,
                                browser=browser,
                                timeout_seconds=float(wv_timeout_seconds),
                                post_load_wait_ms=int(wv_post_load_wait_ms),
                            )

                            # Skip infra-induced browser failures (handled by browser_degraded warnings).
                            if (not r.ok) and bool(r.browser_infra_error):
                                continue

                            # Per-domain overrides via check.py (web_vitals: {...}).
                            cfg = spec.web_vitals if isinstance(spec.web_vitals, dict) else {}
                            lcp_max = _coerce_optional_float(cfg.get("lcp_ms_max", wv_lcp_ms_max))
                            cls_max = _coerce_optional_float(cfg.get("cls_max", wv_cls_max))
                            inp_max = _coerce_optional_float(cfg.get("inp_ms_max", wv_inp_ms_max))

                            thresholds = {"lcp_ms_max": lcp_max, "cls_max": cls_max, "inp_ms_max": inp_max}

                            evaluated = r
                            if r.ok:
                                m = r.metrics or {}
                                lcp = m.get("lcp_ms")
                                cls = m.get("cls")
                                inp = m.get("inp_ms")
                                violations = []
                                try:
                                    if lcp_max is not None and lcp is not None and float(lcp) > float(lcp_max):
                                        violations.append(f"lcp_ms>{float(lcp_max):.0f}")
                                except Exception:
                                    pass
                                try:
                                    if cls_max is not None and cls is not None and float(cls) > float(cls_max):
                                        violations.append(f"cls>{float(cls_max):.3f}")
                                except Exception:
                                    pass
                                try:
                                    if inp_max is not None and inp is not None and float(inp) > float(inp_max):
                                        violations.append(f"inp_ms>{float(inp_max):.0f}")
                                except Exception:
                                    pass
                                if violations:
                                    evaluated = WebVitalsResult(
                                        domain=r.domain,
                                        ok=False,
                                        metrics=r.metrics,
                                        error="threshold_exceeded: " + ",".join(violations),
                                        elapsed_ms=r.elapsed_ms,
                                        browser_infra_error=r.browser_infra_error,
                                    )

                            observed_ok = bool(evaluated.ok)
                            prev_effective = web_vitals_last_ok.get(spec.domain, True)
                            (
                                next_effective,
                                next_fail,
                                next_success,
                                alerted_down,
                            ) = _update_effective_ok(
                                prev_effective_ok=bool(prev_effective),
                                observed_ok=observed_ok,
                                fail_streak=int(web_vitals_fail_streak.get(spec.domain, 0)),
                                success_streak=int(web_vitals_success_streak.get(spec.domain, 0)),
                                down_after_failures=wv_down_after_failures,
                                up_after_successes=wv_up_after_successes,
                            )
                            web_vitals_last_ok[spec.domain] = next_effective
                            web_vitals_fail_streak[spec.domain] = next_fail
                            web_vitals_success_streak[spec.domain] = next_success

                            if alerted_down and (not evaluated.ok):
                                domain_entry = entries_by_domain[spec.domain]
                                _append_event(
                                    "web_vitals_degraded",
                                    ts=float(cycle_started),
                                    domain=spec.domain,
                                    reason=str(evaluated.error or "threshold_exceeded")[:500],
                                    telegram_alert=domain_entry.routes_telegram,
                                    alert_policy=domain_entry.alert_policy.telegram,
                                )
                                msg = _build_web_vitals_alert_message(
                                    failures=[evaluated],
                                    thresholds=thresholds,
                                    down_after_failures=wv_down_after_failures,
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
                                        "Web vitals degraded domain=%s sent_ok=%s telegram_last=%s",
                                        spec.domain,
                                        ok_all,
                                        redact_telegram_response(resps[-1] if resps else {}),
                                    )
                                    wv_failures_for_dispatch.append(evaluated)
                            else:
                                recovered = (not prev_effective) and bool(next_effective)
                                if recovered:
                                    _append_event(
                                        "web_vitals_recovered",
                                        ts=float(cycle_started),
                                        domain=spec.domain,
                                    )
                                if (
                                    recovered
                                    and wv_notify_on_recovery
                                    and entries_by_domain[spec.domain].routes_telegram
                                ):
                                    ok, resp = await send_telegram_message(
                                        http_client,
                                        telegram_cfg,
                                        f"Web vitals recovered ✅ domain={spec.domain}",
                                    )
                                    LOGGER.info(
                                        "Web vitals recovery notice sent_ok=%s telegram=%s domain=%s",
                                        ok,
                                        redact_telegram_response(resp),
                                        spec.domain,
                                    )

                        if wv_failures_for_dispatch and wv_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                            if "web_vitals" in active_dispatch_tasks and not active_dispatch_tasks["web_vitals"].done():
                                LOGGER.info("Dispatch already running for web_vitals; skipping new dispatch")
                            else:
                                active_dispatch_tasks["web_vitals"] = asyncio.create_task(
                                    _dispatch_web_vitals_and_forward(
                                        http_client=http_client,
                                        telegram_cfg=telegram_cfg,
                                        dispatch_cfg=dispatch_cfg,
                                        dispatch_state=dispatch_state,
                                        failures=wv_failures_for_dispatch,
                                        dispatch_history=dispatch_history,
                                        dispatch_last=dispatch_last,
                                        events=events,
                                    )
                                )

                    _append_signal_sample(
                        "browser",
                        [
                            float(cycle_started),
                            0 if browser_degraded else 1,
                            1 if bool(monitor_state.get("browser_degraded_active")) else 0,
                            int(monitor_state.get("browser_launch_fail_count") or 0),
                        ],
                    )

                    if browser_degraded:
                        now_ts = time.time()
                        if not monitor_state.get("browser_degraded_active", False):
                            monitor_state["browser_degraded_active"] = True
                            monitor_state["browser_degraded_first_seen_ts"] = now_ts
                            monitor_state["browser_degraded_recover_streak"] = 0

                        monitor_state["browser_degraded_recover_streak"] = 0
                        last_notice = float(monitor_state.get("browser_degraded_last_notice_ts") or 0.0)
                        min_interval = float(
                            monitor_state.get("browser_degraded_notice_min_interval_seconds") or (6 * 3600)
                        )
                        should_notify = last_notice <= 0.0 or (now_ts - last_notice) >= min_interval
                        if should_notify:
                            monitor_state["browser_degraded_last_notice_ts"] = now_ts
                            LOGGER.warning("Playwright browser checks degraded; restarting browser process")
                            health_hint = _format_browser_health_hint()
                            last_err = monitor_state.get("browser_launch_last_error")
                            lines = [
                                "Monitor warning: Playwright browser checks are degraded (browser crash/close detected).",
                                "Continuing with HTTP-only results and attempting to restart the browser process.",
                            ]
                            if isinstance(last_err, str) and last_err.strip():
                                lines.append(f"Last browser error: {last_err.strip()[:500]}")
                            if health_hint:
                                lines.append(f"Host: {health_hint}")
                            ok, resp = await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "\n".join(lines).strip(),
                            )
                            LOGGER.warning(
                                "Browser degraded notice sent ok=%s telegram=%s",
                                ok,
                                redact_telegram_response(resp),
                            )
                            _append_event(
                                "browser_degraded_notice",
                                ts=float(now_ts),
                                last_error=(last_err.strip()[:800] if isinstance(last_err, str) else None),
                                host_hint=(health_hint.strip()[:500] if isinstance(health_hint, str) else None),
                            )

                            # Persist the notice timestamp immediately (before any risky restart work) to avoid spam
                            # if the process crashes and restarts.
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

                        try:
                            if browser is not None:
                                await browser.close()
                        except Exception:
                            pass
                        browser = None
                        await _ensure_browser(now_ts)
                    else:
                        if monitor_state.get("browser_degraded_active"):
                            streak = int(monitor_state.get("browser_degraded_recover_streak") or 0) + 1
                            monitor_state["browser_degraded_recover_streak"] = streak
                            if streak >= 5:
                                monitor_state["browser_degraded_active"] = False
                                monitor_state["browser_degraded_first_seen_ts"] = 0.0
                                monitor_state["browser_degraded_recover_streak"] = 0
                                LOGGER.info("Playwright browser checks recovered")
                                _append_event("browser_recovered", ts=time.time())

                    # Prune completed dispatch tasks to avoid unbounded growth.
                    for domain, task in list(active_dispatch_tasks.items()):
                        if not task.done():
                            continue
                        try:
                            task.result()
                        except Exception:
                            LOGGER.exception("Dispatch task crashed domain=%s", domain)
                        del active_dispatch_tasks[domain]

                    if heartbeat_enabled and (cycle_results or disabled_lines):
                        now = datetime.now(tz)
                        today = now.date().isoformat()
                        for t in heartbeat_times:
                            hhmm = t.strftime("%H:%M")
                            if last_heartbeat_sent.get(hhmm) == today:
                                continue
                            scheduled_dt = datetime(
                                year=now.year,
                                month=now.month,
                                day=now.day,
                                hour=t.hour,
                                minute=t.minute,
                                tzinfo=tz,
                            )
                            if scheduled_dt <= now < (scheduled_dt + timedelta(seconds=tolerance_seconds)):
                                external_summary = None
                                if external_e2e_enabled and external_e2e_base_url:
                                    if not external_e2e_token:
                                        external_summary = {"ok": False, "error": "missing_e2e_registry_token"}
                                    else:
                                        try:
                                            url = (
                                                external_e2e_base_url.rstrip("/")
                                                + "/api/v1/status/summary"
                                            )
                                            resp = await http_client.get(
                                                url,
                                                headers={"Authorization": f"Bearer {external_e2e_token}"},
                                                timeout=float(external_e2e_timeout_seconds),
                                            )
                                            resp.raise_for_status()
                                            data = resp.json()
                                            if isinstance(data, dict):
                                                external_summary = data
                                            else:
                                                external_summary = {"ok": False, "error": "invalid_e2e_registry_response"}
                                        except Exception as exc:
                                            external_summary = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

                                msg = _build_heartbeat_message(
                                    now=now,
                                    scheduled_label=f"{hhmm} {heartbeat_timezone}",
                                    started_at=started_at,
                                    results=cycle_results,
                                    domain_entries=entries_by_domain,
                                    disabled_lines=disabled_lines,
                                    host_snap=host_snap,
                                    host_violations=host_violations,
                                    perf_slow=perf_slow if perf_enabled else None,
                                    external_e2e=external_summary,
                                )
                                ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                                last_heartbeat_sent[hhmm] = today
                                LOGGER.info(
                                    "Heartbeat sent scheduled=%s ok=%s telegram_last=%s",
                                    hhmm,
                                    ok_all,
                                    redact_telegram_response(resps[-1] if resps else {}),
                                )
                                break

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
                    if meta_enabled:
                        meta_reasons: list[str] = []
                        try:
                            overrun_threshold = float(interval_seconds) * float(meta_cycle_overrun_factor)
                        except Exception:
                            overrun_threshold = float(interval_seconds) * 1.25
                        if float(elapsed) > float(overrun_threshold):
                            meta_reasons.append(
                                f"cycle_overrun: elapsed={round(float(elapsed), 3)}s > threshold={round(float(overrun_threshold), 3)}s interval={int(interval_seconds)}s"
                            )
                        if int(state_write_fail_streak) >= int(meta_state_write_failures_max):
                            meta_reasons.append(
                                f"state_write_failures: streak={int(state_write_fail_streak)} >= {int(meta_state_write_failures_max)}"
                            )

                        meta_observed_ok = not bool(meta_reasons)
                        prev_effective = bool(meta_last_ok)
                        meta_last_ok, meta_fail_streak, meta_success_streak, meta_alerted_down = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=meta_observed_ok,
                            fail_streak=int(meta_fail_streak),
                            success_streak=int(meta_success_streak),
                            down_after_failures=meta_down_after_failures,
                            up_after_successes=meta_up_after_successes,
                        )
                        _append_signal_sample(
                            "meta",
                            [
                                float(cycle_started),
                                1 if bool(meta_last_ok) else 0,
                                int(len(meta_reasons or [])),
                                round(float(elapsed), 3),
                                int(state_write_fail_streak),
                            ],
                        )

                        if meta_alerted_down and meta_reasons:
                            _append_event("meta_degraded", ts=float(cycle_started), reasons=meta_reasons[:20])
                            msg = _build_meta_alert_message(
                                reasons=meta_reasons,
                                down_after_failures=meta_down_after_failures,
                                fail_streak=int(meta_fail_streak),
                            )
                            ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                            LOGGER.warning(
                                "Meta degraded alert sent_ok=%s telegram_last=%s reasons=%s",
                                ok_all,
                                redact_telegram_response(resps[-1] if resps else {}),
                                meta_reasons[:3],
                            )

                            if meta_dispatch_on_degraded and dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
                                if "meta" in active_dispatch_tasks and not active_dispatch_tasks["meta"].done():
                                    LOGGER.info("Dispatch already running for meta; skipping new dispatch")
                                else:
                                    active_dispatch_tasks["meta"] = asyncio.create_task(
                                        _dispatch_meta_and_forward(
                                            http_client=http_client,
                                            telegram_cfg=telegram_cfg,
                                            dispatch_cfg=dispatch_cfg,
                                            dispatch_state=dispatch_state,
                                            reasons=meta_reasons,
                                            context={
                                                "interval_seconds": int(interval_seconds),
                                                "elapsed_seconds": round(float(elapsed), 3),
                                                "state_write_fail_streak": int(state_write_fail_streak),
                                                "browser_connected": (
                                                    bool(browser and getattr(browser, "is_connected", lambda: False)())
                                                    if browser is not None
                                                    else False
                                                ),
                                                "check_concurrency": int(check_concurrency),
                                                "browser_concurrency": int(browser_concurrency),
                                            },
                                            dispatch_history=dispatch_history,
                                            dispatch_last=dispatch_last,
                                            events=events,
                                        )
                                    )

                        meta_recovered = (not prev_effective) and bool(meta_last_ok)
                        if meta_recovered:
                            _append_event("meta_recovered", ts=float(cycle_started))
                        if meta_recovered and meta_notify_on_recovery:
                            ok, resp = await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "Monitoring pipeline recovered ✅",
                            )
                            LOGGER.info(
                                "Meta recovery notice sent_ok=%s telegram=%s",
                                ok,
                                redact_telegram_response(resp),
                            )

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
                if browser is not None:
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
