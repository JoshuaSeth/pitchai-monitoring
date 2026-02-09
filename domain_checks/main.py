from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import runpy
import shutil
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, time as dt_time, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from playwright.async_api import Browser, async_playwright
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from domain_checks.common_check import (
    DomainCheckResult,
    DomainCheckSpec,
    browser_check,
    find_chromium_executable,
    http_get_check,
    load_domain_spec_from_module_dict,
)
from domain_checks.history import append_sample, coerce_history, prune_history
from domain_checks.metrics_api_contract import ApiContractCheckResult, run_api_contract_checks
from domain_checks.metrics_container_health import ContainerHealthIssue, check_container_health
from domain_checks.metrics_dns import DnsCheckResult, check_dns
from domain_checks.metrics_nginx import (
    NginxAccessWindowStats,
    NginxUpstreamErrorEvent,
    compute_access_window_stats,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)
from domain_checks.metrics_proxy import ProxyIssue, check_upstream_header_expectations
from domain_checks.metrics_red import RedViolation, compute_red_violations
from domain_checks.metrics_slo import SloBurnViolation, compute_slo_burn_violations
from domain_checks.metrics_synthetic import SyntheticTransactionResult, run_synthetic_transactions
from domain_checks.metrics_tls import TlsCertCheckResult, check_tls_certs
from domain_checks.metrics_web_vitals import WebVitalsResult, measure_web_vitals
from domain_checks.dispatch_client import (
    DispatchConfig,
    dispatch_job,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    get_last_agent_message,
    get_run_log_tail,
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


@dataclass(frozen=True)
class DomainEntryConfig:
    domain: str
    raw_entry: Any
    disabled: bool = False
    disabled_reason: str | None = None
    disabled_until_ts: float | None = None

    def is_disabled(self, now_ts: float) -> bool:
        if self.disabled:
            return True
        if self.disabled_until_ts is not None and now_ts < float(self.disabled_until_ts):
            return True
        return False


def _parse_disabled_until_ts(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        ts = float(value)
        return ts if ts > 0 else None

    s = str(value or "").strip()
    if not s:
        return None

    try:
        ts = float(s)
        return ts if ts > 0 else None
    except Exception:
        pass

    s_iso = s
    if s_iso.endswith("Z"):
        s_iso = s_iso[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        try:
            d = date.fromisoformat(s)
        except Exception as exc:
            raise ValueError(
                f"Invalid disabled_until value {value!r}; expected unix timestamp or ISO-8601 datetime/date"
            ) from exc
        dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        return dt.timestamp()


def _normalize_domain_entries(domains_cfg: list[Any]) -> list[DomainEntryConfig]:
    entries: list[DomainEntryConfig] = []
    forced_disabled = {
        # Dispatcher runs on a different server and is not an app/site we want uptime/UI checks for.
        # Keeping it here prevents accidental addition causing alert noise.
        "dispatch.pitchai.net",
    }

    for idx, entry in enumerate(domains_cfg):
        if isinstance(entry, str):
            domain = entry.strip()
            if not domain:
                raise ValueError(f"domains[{idx}] is empty")
            if domain in forced_disabled:
                entries.append(
                    DomainEntryConfig(
                        domain=domain,
                        raw_entry=domain,
                        disabled=True,
                        disabled_reason="excluded from monitoring (dispatcher runs elsewhere)",
                    )
                )
            else:
                entries.append(DomainEntryConfig(domain=domain, raw_entry=domain))
            continue

        if not isinstance(entry, dict):
            raise ValueError(f"domains[{idx}] must be a string or mapping, got {type(entry).__name__}")

        domain = str(entry.get("domain") or "").strip()
        if not domain:
            raise ValueError(f"domains[{idx}].domain is required")

        disabled = bool(entry.get("disabled")) or (entry.get("enabled") is False)
        disabled_reason = str(entry.get("disabled_reason") or "").strip() or None
        disabled_until_ts = _parse_disabled_until_ts(entry.get("disabled_until"))

        if domain in forced_disabled:
            disabled = True
            if not disabled_reason:
                disabled_reason = "excluded from monitoring (dispatcher runs elsewhere)"

        entries.append(
            DomainEntryConfig(
                domain=domain,
                raw_entry=entry,
                disabled=disabled,
                disabled_reason=disabled_reason,
                disabled_until_ts=disabled_until_ts,
            )
        )

    seen: set[str] = set()
    for entry in entries:
        if entry.domain in seen:
            raise ValueError(f"Duplicate domain entry: {entry.domain}")
        seen.add(entry.domain)

    return entries


def _format_disabled_domain_line(entry: DomainEntryConfig, tz) -> str:
    parts = ["DISABLED"]
    if entry.disabled_until_ts is not None and float(entry.disabled_until_ts) > 0:
        until = datetime.fromtimestamp(float(entry.disabled_until_ts), tz=tz)
        parts.append(f"until {until.strftime('%Y-%m-%d %H:%M %Z')}")
    if entry.disabled_reason:
        parts.append(f"({entry.disabled_reason})")
    return f"- {entry.domain}: {' '.join(parts)}"


def _parse_hhmm(value: Any) -> dt_time:
    s = str(value or "").strip()
    if not s or ":" not in s:
        raise ValueError(f"Invalid time (expected HH:MM): {value!r}")
    hh_str, mm_str = s.split(":", 1)
    hour = int(hh_str)
    minute = int(mm_str)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time (expected HH:MM): {value!r}")
    return dt_time(hour=hour, minute=minute)


def _get_heartbeat_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("heartbeat") or {}
    return raw if isinstance(raw, dict) else {}


def _get_host_health_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("host_health") or {}
    return raw if isinstance(raw, dict) else {}


def _get_performance_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("performance") or {}
    return raw if isinstance(raw, dict) else {}


def _get_history_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("history") or {}
    return raw if isinstance(raw, dict) else {}


def _get_slo_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("slo") or {}
    return raw if isinstance(raw, dict) else {}


def _get_tls_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("tls") or {}
    return raw if isinstance(raw, dict) else {}


def _get_dns_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("dns") or {}
    return raw if isinstance(raw, dict) else {}


def _get_red_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("red") or {}
    return raw if isinstance(raw, dict) else {}


def _get_synthetic_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("synthetic") or {}
    return raw if isinstance(raw, dict) else {}


def _get_web_vitals_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("web_vitals") or {}
    return raw if isinstance(raw, dict) else {}


def _get_api_contract_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("api_contract") or {}
    return raw if isinstance(raw, dict) else {}


def _get_container_health_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("container_health") or {}
    return raw if isinstance(raw, dict) else {}


def _get_proxy_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("proxy") or {}
    return raw if isinstance(raw, dict) else {}


def _get_meta_monitoring_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("meta_monitoring") or {}
    return raw if isinstance(raw, dict) else {}


def _load_timezone(name: str):
    cleaned = (name or "").strip()
    if not cleaned or cleaned.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        LOGGER.warning("Timezone not found; falling back to UTC tz=%s", cleaned)
        return timezone.utc


def _format_ms(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{int(round(float(value)))}ms"
    except Exception:
        return "n/a"


def _format_uptime(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, rem = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02}h {minutes:02}m"
    if hours:
        return f"{hours}h {minutes:02}m"
    return f"{minutes}m {rem:02}s"


def _build_down_alert_message(result: DomainCheckResult) -> str:
    d = result.details or {}
    lines = [f"{result.domain} is DOWN ❌", f"Reason: {result.reason}"]

    fail_streak = d.get("fail_streak")
    down_after = d.get("down_after_failures")
    if isinstance(fail_streak, int) and isinstance(down_after, int) and down_after > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after}")

    status_code = d.get("status_code")
    http_ms = d.get("http_elapsed_ms")
    if status_code is not None:
        lines.append(f"HTTP: {status_code} ({_format_ms(http_ms)})")

    browser_status = d.get("http_status")
    browser_ms = d.get("browser_elapsed_ms")
    if browser_status is not None:
        lines.append(f"Browser: {browser_status} ({_format_ms(browser_ms)})")

    final_url = d.get("final_url")
    if isinstance(final_url, str) and final_url:
        lines.append(f"Final URL: {final_url}")

    if d.get("final_host_ok") is False:
        final_host = d.get("final_host")
        expected_suffix = d.get("expected_final_host_suffix")
        lines.append(f"Final host mismatch: got={final_host} expected_suffix={expected_suffix}")

    if d.get("title_ok") is False:
        title = d.get("title")
        lines.append(f"Title mismatch: {title!r}")

    error = d.get("error")
    if isinstance(error, str) and error.strip():
        lines.append(f"Error: {error.strip()[:500]}")

    forbidden_hits = d.get("forbidden_hits") or []
    if isinstance(forbidden_hits, list) and forbidden_hits:
        hits = ", ".join(str(x) for x in forbidden_hits[:8])
        lines.append(f"Forbidden text hit: {hits}")

    missing_all = d.get("missing_selectors_all") or []
    if isinstance(missing_all, list) and missing_all:
        missing = ", ".join(str(x) for x in missing_all[:5])
        lines.append(f"Missing selectors: {missing}")

    missing_text = d.get("missing_text") or []
    if isinstance(missing_text, list) and missing_text:
        missing = ", ".join(str(x) for x in missing_text[:5])
        lines.append(f"Missing text: {missing}")

    return "\n".join(lines).strip()


def _dispatch_state_reenable_if_due(dispatch_state: dict[str, Any]) -> None:
    if dispatch_state.get("enabled") is True:
        return
    disabled_until = dispatch_state.get("disabled_until_monotonic")
    if disabled_until is None:
        return  # permanently disabled
    if time.monotonic() >= float(disabled_until):
        dispatch_state["enabled"] = True
        dispatch_state["disabled_until_monotonic"] = None
        dispatch_state["disabled_reason"] = None


def _dispatch_is_enabled(dispatch_cfg: DispatchConfig | None, dispatch_state: dict[str, Any]) -> bool:
    if not dispatch_cfg:
        return False
    _dispatch_state_reenable_if_due(dispatch_state)
    return bool(dispatch_state.get("enabled", True))


def _dispatch_disable(
    dispatch_state: dict[str, Any],
    *,
    reason: str,
    cooldown_seconds: float | None = None,
) -> None:
    dispatch_state["enabled"] = False
    dispatch_state["disabled_reason"] = reason
    if cooldown_seconds is None:
        dispatch_state["disabled_until_monotonic"] = None
    else:
        dispatch_state["disabled_until_monotonic"] = time.monotonic() + max(1.0, float(cooldown_seconds))


def _dispatch_should_notify(dispatch_state: dict[str, Any], *, min_interval_seconds: float = 3600.0) -> bool:
    last = float(dispatch_state.get("last_notify_monotonic") or 0.0)
    now = time.monotonic()
    if (now - last) >= float(min_interval_seconds):
        dispatch_state["last_notify_monotonic"] = now
        return True
    return False


async def _notify_dispatch_disabled(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_state: dict[str, Any],
    details: str,
) -> None:
    reason = dispatch_state.get("disabled_reason") or "unknown"
    until = dispatch_state.get("disabled_until_monotonic")
    if until is None and dispatch_state.get("enabled") is False:
        until_txt = "until token is fixed/restarted"
    else:
        until_txt = "temporarily"
    msg = (
        "Dispatcher escalation is disabled.\n"
        f"Reason: {reason}\n"
        f"Status: {until_txt}\n"
        f"Details: {details}"
    )
    await send_telegram_message(http_client, telegram_cfg, msg)


def _collect_performance_violations(
    results: dict[str, DomainCheckResult],
    *,
    http_elapsed_ms_max: float,
    browser_elapsed_ms_max: float,
    per_domain_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Returns a list of slow-domain entries (non-empty => observed performance degraded).

    Each entry includes:
    - domain
    - http_ms / http_max_ms
    - browser_ms / browser_max_ms (if present)
    - reasons: list[str]
    """
    overrides = per_domain_overrides if isinstance(per_domain_overrides, dict) else {}
    slow: list[dict[str, Any]] = []

    for domain in sorted(results.keys()):
        result = results[domain]
        if not result.ok:
            continue  # DOWN alerts handle this path; don't mix with perf warnings.
        details = result.details or {}

        override = overrides.get(domain) if isinstance(overrides.get(domain), dict) else {}
        http_max = float(override.get("http_elapsed_ms_max", http_elapsed_ms_max))
        browser_max = float(override.get("browser_elapsed_ms_max", browser_elapsed_ms_max))

        http_ms = details.get("http_elapsed_ms")
        browser_ms = details.get("browser_elapsed_ms")

        reasons: list[str] = []
        http_ms_f = None
        try:
            if http_ms is not None:
                http_ms_f = float(http_ms)
                if http_ms_f > http_max:
                    reasons.append(f"http>{int(round(http_max))}ms")
        except Exception:
            http_ms_f = None

        browser_ms_f = None
        try:
            if browser_ms is not None:
                browser_ms_f = float(browser_ms)
                if browser_ms_f > browser_max:
                    reasons.append(f"browser>{int(round(browser_max))}ms")
        except Exception:
            browser_ms_f = None

        if reasons:
            slow.append(
                {
                    "domain": domain,
                    "http_ms": http_ms_f,
                    "http_max_ms": http_max,
                    "browser_ms": browser_ms_f,
                    "browser_max_ms": browser_max,
                    "reasons": reasons,
                }
            )

    return slow


def _build_host_health_alert_message(
    *,
    violations: list[str],
    snap: dict[str, Any],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: host health thresholds exceeded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    lines.extend(f"- {v}" for v in violations[:10])

    extra: list[str] = []
    disk = snap.get("disk") if isinstance(snap.get("disk"), dict) else {}
    if disk:
        # Include the worst path in a stable order (already computed in violations, but this is for heartbeat context).
        worst_path = None
        worst_pct = None
        for path, info in disk.items():
            if not isinstance(info, dict):
                continue
            pct = info.get("used_percent")
            try:
                pct_f = float(pct)
            except Exception:
                continue
            if worst_pct is None or pct_f > worst_pct:
                worst_pct = pct_f
                worst_path = str(path)
        if worst_path and worst_pct is not None:
            extra.append(f"Disk worst: {worst_path} {_format_percent(worst_pct)}")

    mem_used = snap.get("mem_used_percent")
    if mem_used is not None:
        extra.append(f"Mem used: {_format_percent(mem_used)}")

    swap_used = snap.get("swap_used_percent")
    if swap_used is not None:
        extra.append(f"Swap used: {_format_percent(swap_used)}")

    cpu_used = snap.get("cpu_used_percent")
    if cpu_used is not None:
        extra.append(f"CPU used: {_format_percent(cpu_used)}")

    load1 = snap.get("load1")
    load1pc = snap.get("load1_per_cpu")
    try:
        if load1 is not None:
            if load1pc is not None:
                extra.append(f"Load: {float(load1):.1f} (per_cpu={float(load1pc):.2f})")
            else:
                extra.append(f"Load: {float(load1):.1f}")
    except Exception:
        pass

    if extra:
        lines.append("")
        lines.extend(extra[:6])

    return "\n".join(lines).strip()


def _build_performance_alert_message(
    *,
    slow: list[dict[str, Any]],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: website performance is degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    lines.append("Slow domains (HTTP / Browser):")
    for entry in slow[:12]:
        domain = entry.get("domain")
        http_ms = _format_ms(entry.get("http_ms"))
        browser_ms = _format_ms(entry.get("browser_ms"))
        reasons = entry.get("reasons") or []
        reason_txt = ",".join(str(x) for x in reasons[:3]) if reasons else "slow"
        lines.append(f"- {domain}: {http_ms} / {browser_ms} ({reason_txt})")
    return "\n".join(lines).strip()


def _build_heartbeat_message(
    *,
    now: datetime,
    scheduled_label: str,
    started_at: datetime,
    results: dict[str, DomainCheckResult],
    disabled_lines: list[str] | None = None,
    host_snap: dict[str, Any] | None = None,
    host_violations: list[str] | None = None,
    perf_slow: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        "Heartbeat: service-monitoring is running ✅",
        f"Scheduled: {scheduled_label}",
        f"Now: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Uptime: {_format_uptime(now - started_at)}",
    ]

    if isinstance(host_snap, dict) and host_snap:
        lines.append("")
        lines.append("Host health:")
        if host_violations:
            lines.append(f"- Status: DEGRADED ({len(host_violations)} issue(s))")
        else:
            lines.append("- Status: OK")

        disk = host_snap.get("disk") if isinstance(host_snap.get("disk"), dict) else {}
        if disk:
            worst_path = None
            worst_pct = None
            for path, info in disk.items():
                if not isinstance(info, dict):
                    continue
                pct = info.get("used_percent")
                try:
                    pct_f = float(pct)
                except Exception:
                    continue
                if worst_pct is None or pct_f > worst_pct:
                    worst_pct = pct_f
                    worst_path = str(path)
            if worst_path and worst_pct is not None:
                lines.append(f"- Disk: {worst_path} {_format_percent(worst_pct)}")
        if host_snap.get("mem_used_percent") is not None:
            lines.append(f"- Mem used: {_format_percent(host_snap.get('mem_used_percent'))}")
        if host_snap.get("swap_used_percent") is not None:
            lines.append(f"- Swap used: {_format_percent(host_snap.get('swap_used_percent'))}")
        if host_snap.get("cpu_used_percent") is not None:
            lines.append(f"- CPU used: {_format_percent(host_snap.get('cpu_used_percent'))}")
        if host_snap.get("load1") is not None:
            try:
                l1 = float(host_snap.get("load1"))
                lpc = host_snap.get("load1_per_cpu")
                if lpc is not None:
                    lines.append(f"- Load: {l1:.1f} (per_cpu={float(lpc):.2f})")
                else:
                    lines.append(f"- Load: {l1:.1f}")
            except Exception:
                pass

        if host_violations:
            lines.append("- Violations:")
            lines.extend(f"  - {v}" for v in host_violations[:5])

    if perf_slow is not None:
        lines.append("")
        if perf_slow:
            lines.append(f"Performance: DEGRADED (slow_domains={len(perf_slow)})")
            for entry in perf_slow[:5]:
                domain = entry.get("domain")
                http_ms = _format_ms(entry.get("http_ms"))
                browser_ms = _format_ms(entry.get("browser_ms"))
                lines.append(f"- {domain}: {http_ms} / {browser_ms}")
        else:
            lines.append("Performance: OK")

    lines.append("")
    lines.append("Domains (HTTP / Browser):")

    for domain in sorted(results.keys()):
        result = results[domain]
        details = result.details or {}
        http_status = details.get("status_code")
        http_ms = _format_ms(details.get("http_elapsed_ms"))
        browser_ms = _format_ms(details.get("browser_elapsed_ms"))

        if result.ok:
            status_part = f"UP ({http_status})" if http_status is not None else "UP"
            lines.append(f"- {domain}: {status_part} {http_ms} / {browser_ms}")
            continue

        reason = result.reason or "down"
        if isinstance(details.get("error"), str) and details["error"].strip():
            reason = f"{reason}: {details['error']}"
        status_part = f"DOWN ({reason})"
        if http_status is not None:
            status_part = f"DOWN ({http_status}, {reason})"
        lines.append(f"- {domain}: {status_part} {http_ms} / {browser_ms}")

    if disabled_lines:
        lines.append("")
        lines.append("Disabled (skipped):")
        lines.extend(disabled_lines)

    return "\n".join(lines).strip() + "\n"


def _coerce_bool_dict(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    state: dict[str, bool] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, bool):
            state[k] = v
    return state


def _coerce_int_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    state: dict[str, int] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            continue
        try:
            state[k] = int(v)
        except Exception:
            continue
    return state


def _coerce_float_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    state: dict[str, float] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            continue
        try:
            state[k] = float(v)
        except Exception:
            continue
    return state


def _coerce_str_list_dict(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            continue
        if not isinstance(v, list):
            continue
        items: list[str] = []
        for x in v:
            s = str(x or "").strip()
            if s:
                items.append(s)
        out[k] = items
    return out


def _coerce_bool(value: Any, *, default: bool) -> bool:
    return value if isinstance(value, bool) else bool(default)


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _coerce_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _load_monitor_state(path: Path) -> dict[str, Any]:
    default_state = {
        "last_ok": {},
        "fail_streak": {},
        "success_streak": {},
        "history": {},
        "browser_degraded_last_notice_ts": 0.0,
        "host_health": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
            "cpu_prev_total": 0,
            "cpu_prev_idle": 0,
        },
        "performance": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
        },
        "slo": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
        },
        "tls": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
            "last_run_ts": 0.0,
        },
        "dns": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
            "last_run_ts": 0.0,
            "last_ips": {},
        },
        "red": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
        },
        "synthetic": {
            "last_ok": {},
            "fail_streak": {},
            "success_streak": {},
            "last_run_ts": {},
        },
        "web_vitals": {
            "last_ok": {},
            "fail_streak": {},
            "success_streak": {},
            "last_run_ts": {},
        },
        "api_contract": {
            "last_ok": {},
            "fail_streak": {},
            "success_streak": {},
            "last_run_ts": {},
        },
        "container_health": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
            "last_run_ts": 0.0,
            "restart_counts": {},
        },
        "proxy": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
        },
        "meta": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 0,
            "state_write_fail_streak": 0,
        },
    }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_state
    except Exception as exc:
        LOGGER.warning("Failed to read state file path=%s error=%s", path, exc)
        return default_state

    if not isinstance(raw, dict):
        return default_state

    # Back-compat: previously stored only {"last_ok": {...}} or raw mapping.
    if isinstance(raw.get("last_ok"), dict) and not any(k in raw for k in ("fail_streak", "success_streak")):
        state = dict(default_state)
        state["last_ok"] = _coerce_bool_dict(raw.get("last_ok"))
        return state

    if all(isinstance(v, bool) for v in raw.values()):
        state = dict(default_state)
        state["last_ok"] = _coerce_bool_dict(raw)
        return state

    last_notice_ts = 0.0
    try:
        last_notice_ts = float(raw.get("browser_degraded_last_notice_ts") or 0.0)
    except Exception:
        last_notice_ts = 0.0

    state = dict(default_state)
    state["last_ok"] = _coerce_bool_dict(raw.get("last_ok"))
    state["fail_streak"] = _coerce_int_dict(raw.get("fail_streak"))
    state["success_streak"] = _coerce_int_dict(raw.get("success_streak"))
    state["history"] = coerce_history(raw.get("history"))
    state["browser_degraded_last_notice_ts"] = last_notice_ts

    host = raw.get("host_health")
    if isinstance(host, dict):
        state["host_health"] = {
            "last_ok": _coerce_bool(host.get("last_ok"), default=True),
            "fail_streak": _coerce_int(host.get("fail_streak"), default=0),
            "success_streak": _coerce_int(host.get("success_streak"), default=0),
            "cpu_prev_total": _coerce_int(host.get("cpu_prev_total"), default=0),
            "cpu_prev_idle": _coerce_int(host.get("cpu_prev_idle"), default=0),
        }

    perf = raw.get("performance")
    if isinstance(perf, dict):
        state["performance"] = {
            "last_ok": _coerce_bool(perf.get("last_ok"), default=True),
            "fail_streak": _coerce_int(perf.get("fail_streak"), default=0),
            "success_streak": _coerce_int(perf.get("success_streak"), default=0),
        }

    slo = raw.get("slo")
    if isinstance(slo, dict):
        state["slo"] = {
            "last_ok": _coerce_bool(slo.get("last_ok"), default=True),
            "fail_streak": _coerce_int(slo.get("fail_streak"), default=0),
            "success_streak": _coerce_int(slo.get("success_streak"), default=0),
        }

    tls = raw.get("tls")
    if isinstance(tls, dict):
        state["tls"] = {
            "last_ok": _coerce_bool(tls.get("last_ok"), default=True),
            "fail_streak": _coerce_int(tls.get("fail_streak"), default=0),
            "success_streak": _coerce_int(tls.get("success_streak"), default=0),
            "last_run_ts": _coerce_float(tls.get("last_run_ts"), default=0.0),
        }

    dns = raw.get("dns")
    if isinstance(dns, dict):
        state["dns"] = {
            "last_ok": _coerce_bool(dns.get("last_ok"), default=True),
            "fail_streak": _coerce_int(dns.get("fail_streak"), default=0),
            "success_streak": _coerce_int(dns.get("success_streak"), default=0),
            "last_run_ts": _coerce_float(dns.get("last_run_ts"), default=0.0),
            "last_ips": _coerce_str_list_dict(dns.get("last_ips")),
        }

    red = raw.get("red")
    if isinstance(red, dict):
        state["red"] = {
            "last_ok": _coerce_bool(red.get("last_ok"), default=True),
            "fail_streak": _coerce_int(red.get("fail_streak"), default=0),
            "success_streak": _coerce_int(red.get("success_streak"), default=0),
        }

    synthetic = raw.get("synthetic")
    if isinstance(synthetic, dict):
        state["synthetic"] = {
            "last_ok": _coerce_bool_dict(synthetic.get("last_ok")),
            "fail_streak": _coerce_int_dict(synthetic.get("fail_streak")),
            "success_streak": _coerce_int_dict(synthetic.get("success_streak")),
            "last_run_ts": _coerce_float_dict(synthetic.get("last_run_ts")),
        }

    web_vitals = raw.get("web_vitals")
    if isinstance(web_vitals, dict):
        state["web_vitals"] = {
            "last_ok": _coerce_bool_dict(web_vitals.get("last_ok")),
            "fail_streak": _coerce_int_dict(web_vitals.get("fail_streak")),
            "success_streak": _coerce_int_dict(web_vitals.get("success_streak")),
            "last_run_ts": _coerce_float_dict(web_vitals.get("last_run_ts")),
        }

    api_contract = raw.get("api_contract")
    if isinstance(api_contract, dict):
        state["api_contract"] = {
            "last_ok": _coerce_bool_dict(api_contract.get("last_ok")),
            "fail_streak": _coerce_int_dict(api_contract.get("fail_streak")),
            "success_streak": _coerce_int_dict(api_contract.get("success_streak")),
            "last_run_ts": _coerce_float_dict(api_contract.get("last_run_ts")),
        }

    container_health = raw.get("container_health")
    if isinstance(container_health, dict):
        state["container_health"] = {
            "last_ok": _coerce_bool(container_health.get("last_ok"), default=True),
            "fail_streak": _coerce_int(container_health.get("fail_streak"), default=0),
            "success_streak": _coerce_int(container_health.get("success_streak"), default=0),
            "last_run_ts": _coerce_float(container_health.get("last_run_ts"), default=0.0),
            "restart_counts": _coerce_int_dict(container_health.get("restart_counts")),
        }

    proxy = raw.get("proxy")
    if isinstance(proxy, dict):
        state["proxy"] = {
            "last_ok": _coerce_bool(proxy.get("last_ok"), default=True),
            "fail_streak": _coerce_int(proxy.get("fail_streak"), default=0),
            "success_streak": _coerce_int(proxy.get("success_streak"), default=0),
        }

    meta = raw.get("meta")
    if isinstance(meta, dict):
        state["meta"] = {
            "last_ok": _coerce_bool(meta.get("last_ok"), default=True),
            "fail_streak": _coerce_int(meta.get("fail_streak"), default=0),
            "success_streak": _coerce_int(meta.get("success_streak"), default=0),
            "state_write_fail_streak": _coerce_int(meta.get("state_write_fail_streak"), default=0),
        }

    return state


def _load_last_ok_state(path: Path) -> dict[str, bool]:
    return dict(_load_monitor_state(path).get("last_ok") or {})


def _update_effective_ok(
    *,
    prev_effective_ok: bool,
    observed_ok: bool,
    fail_streak: int,
    success_streak: int,
    down_after_failures: int,
    up_after_successes: int,
) -> tuple[bool, int, int, bool]:
    down_after_failures = max(1, int(down_after_failures))
    up_after_successes = max(1, int(up_after_successes))

    if observed_ok:
        success_streak = int(success_streak) + 1
        fail_streak = 0
    else:
        fail_streak = int(fail_streak) + 1
        success_streak = 0

    if prev_effective_ok:
        next_effective_ok = not (fail_streak >= down_after_failures)
    else:
        next_effective_ok = bool(success_streak >= up_after_successes)

    alerted_down = bool(prev_effective_ok and not next_effective_ok)
    return next_effective_ok, fail_streak, success_streak, alerted_down


def _write_state_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_linux_meminfo_kb() -> dict[str, int]:
    """
    Best-effort host memory snapshot for diagnostics (Linux only).
    On macOS/Windows, returns {}.
    """
    try:
        raw = Path("/proc/meminfo").read_text(encoding="utf-8")
    except Exception:
        return {}

    values: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            values[key.strip()] = int(parts[0])
        except Exception:
            continue
    return values


def _format_browser_health_hint() -> str:
    info = _read_linux_meminfo_kb()
    if not info:
        return ""

    def _mb(key: str) -> str:
        v = info.get(key)
        if v is None:
            return "?"
        return str(int(v / 1024))

    mem_avail = _mb("MemAvailable")
    swap_total = _mb("SwapTotal")
    swap_free = _mb("SwapFree")
    swap_used = "?"
    try:
        if swap_total != "?" and swap_free != "?":
            swap_used = str(int(swap_total) - int(swap_free))
    except Exception:
        swap_used = "?"

    try:
        load1, load5, load15 = os.getloadavg()
        load = f"{load1:.1f}/{load5:.1f}/{load15:.1f}"
    except Exception:
        load = "?"

    return f"mem_avail_mb={mem_avail} swap_used_mb={swap_used}/{swap_total} load={load}"


def _read_linux_proc_stat_cpu_total_idle() -> tuple[int, int] | None:
    """
    Return (total_jiffies, idle_jiffies) from /proc/stat for the aggregate CPU line.
    Linux-only; returns None on non-Linux or parse failures.
    """
    try:
        raw = Path("/proc/stat").read_text(encoding="utf-8")
    except Exception:
        return None

    for line in raw.splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()
        # cpu user nice system idle iowait irq softirq steal guest guest_nice
        nums: list[int] = []
        for p in parts[1:]:
            try:
                nums.append(int(p))
            except Exception:
                nums.append(0)
        if len(nums) < 4:
            return None
        total = int(sum(nums))
        idle = int(nums[3] + (nums[4] if len(nums) > 4 else 0))
        return total, idle
    return None


def _compute_cpu_used_percent(
    *, prev_total: int, prev_idle: int, cur_total: int, cur_idle: int
) -> float | None:
    delta_total = int(cur_total) - int(prev_total)
    delta_idle = int(cur_idle) - int(prev_idle)
    if delta_total <= 0:
        return None
    used = max(0.0, min(100.0, (1.0 - (delta_idle / float(delta_total))) * 100.0))
    return round(used, 3)


def _disk_usage_percent(path: str) -> float | None:
    try:
        total, used, _free = shutil.disk_usage(path)
    except Exception:
        return None
    if total <= 0:
        return None
    return round((used / float(total)) * 100.0, 3)


def _format_percent(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value):.1f}%"
    except Exception:
        return "n/a"


def _collect_host_snapshot(*, disk_paths: list[str], cpu_prev_total: int, cpu_prev_idle: int) -> dict[str, Any]:
    meminfo = _read_linux_meminfo_kb()
    mem_total_kb = meminfo.get("MemTotal")
    mem_avail_kb = meminfo.get("MemAvailable")
    mem_used_pct = None
    if isinstance(mem_total_kb, int) and mem_total_kb > 0 and isinstance(mem_avail_kb, int):
        mem_used_pct = round((1.0 - (mem_avail_kb / float(mem_total_kb))) * 100.0, 3)

    swap_total_kb = meminfo.get("SwapTotal")
    swap_free_kb = meminfo.get("SwapFree")
    swap_used_pct = None
    if isinstance(swap_total_kb, int) and swap_total_kb > 0 and isinstance(swap_free_kb, int):
        swap_used_pct = round((1.0 - (swap_free_kb / float(swap_total_kb))) * 100.0, 3)

    disk: dict[str, Any] = {}
    for p in disk_paths:
        pp = str(p or "").strip()
        if not pp:
            continue
        if not Path(pp).exists():
            continue
        disk_pct = _disk_usage_percent(pp)
        if disk_pct is None:
            continue
        disk[pp] = {"used_percent": disk_pct}

    cpu_used_pct = None
    cpu_cur = _read_linux_proc_stat_cpu_total_idle()
    cpu_prev_total = int(cpu_prev_total) if cpu_prev_total else 0
    cpu_prev_idle = int(cpu_prev_idle) if cpu_prev_idle else 0
    cpu_cur_total = None
    cpu_cur_idle = None
    if cpu_cur is not None:
        cpu_cur_total, cpu_cur_idle = cpu_cur
        if cpu_prev_total > 0 and cpu_prev_idle > 0:
            cpu_used_pct = _compute_cpu_used_percent(
                prev_total=cpu_prev_total,
                prev_idle=cpu_prev_idle,
                cur_total=cpu_cur_total,
                cur_idle=cpu_cur_idle,
            )

    load1 = load5 = load15 = None
    try:
        l1, l5, l15 = os.getloadavg()
        load1, load5, load15 = float(l1), float(l5), float(l15)
    except Exception:
        pass

    cpu_count = os.cpu_count() or 0
    load1_per_cpu = None
    if load1 is not None and cpu_count > 0:
        load1_per_cpu = round(load1 / float(cpu_count), 3)

    snap: dict[str, Any] = {
        "mem_total_kb": mem_total_kb,
        "mem_available_kb": mem_avail_kb,
        "mem_used_percent": mem_used_pct,
        "swap_total_kb": swap_total_kb,
        "swap_free_kb": swap_free_kb,
        "swap_used_percent": swap_used_pct,
        "disk": disk,
        "cpu_used_percent": cpu_used_pct,
        "cpu_count": cpu_count,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "load1_per_cpu": load1_per_cpu,
        "cpu_prev_total_next": cpu_cur_total,
        "cpu_prev_idle_next": cpu_cur_idle,
    }
    return snap


def _collect_host_health_violations(
    snap: dict[str, Any],
    *,
    disk_used_percent_max: float | None,
    mem_used_percent_max: float | None,
    swap_used_percent_max: float | None,
    cpu_used_percent_max: float | None,
    load1_per_cpu_max: float | None,
) -> list[str]:
    violations: list[str] = []

    if disk_used_percent_max is not None:
        worst_path = None
        worst_pct = None
        disk = snap.get("disk") if isinstance(snap.get("disk"), dict) else {}
        for path, info in disk.items():
            if not isinstance(info, dict):
                continue
            pct = info.get("used_percent")
            try:
                pct_f = float(pct)
            except Exception:
                continue
            if worst_pct is None or pct_f > worst_pct:
                worst_pct = pct_f
                worst_path = str(path)
        if worst_pct is not None and worst_pct >= float(disk_used_percent_max):
            violations.append(f"Disk {worst_path}: {_format_percent(worst_pct)} >= {_format_percent(disk_used_percent_max)}")

    if mem_used_percent_max is not None:
        pct = snap.get("mem_used_percent")
        try:
            pct_f = float(pct)
        except Exception:
            pct_f = None
        if pct_f is not None and pct_f >= float(mem_used_percent_max):
            violations.append(f"Memory: {_format_percent(pct_f)} >= {_format_percent(mem_used_percent_max)}")

    if swap_used_percent_max is not None:
        pct = snap.get("swap_used_percent")
        try:
            pct_f = float(pct)
        except Exception:
            pct_f = None
        if pct_f is not None and pct_f >= float(swap_used_percent_max):
            violations.append(f"Swap: {_format_percent(pct_f)} >= {_format_percent(swap_used_percent_max)}")

    if cpu_used_percent_max is not None:
        pct = snap.get("cpu_used_percent")
        try:
            pct_f = float(pct)
        except Exception:
            pct_f = None
        if pct_f is not None and pct_f >= float(cpu_used_percent_max):
            violations.append(f"CPU: {_format_percent(pct_f)} >= {_format_percent(cpu_used_percent_max)}")

    if load1_per_cpu_max is not None:
        v = snap.get("load1_per_cpu")
        try:
            v_f = float(v)
        except Exception:
            v_f = None
        if v_f is not None and v_f >= float(load1_per_cpu_max):
            violations.append(f"Load1/CPU: {v_f:.2f} >= {float(load1_per_cpu_max):.2f}")

    return violations


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
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        f"1) Investigate why {result.domain} is not functioning properly on the production host.\n"
        "2) Use Docker to identify the relevant service container(s) and reverse proxy (by name/image/labels/ports).\n"
        "3) Inspect container status, recent restarts, health checks, and logs.\n"
        "4) Check for common root causes: upstream crash-loop, bad deploy, DNS, cert expiry, proxy config, "
        "resource exhaustion, and disk space issues.\n"
        "5) If you believe a restart or configuration change would help, suggest it as a human action but do not execute it.\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Commands run (read-only diagnostics)\n"
        "- Current status + what to monitor next\n"
    )


def _dispatch_read_only_rules() -> str:
    return (
        "IMPORTANT safety rules:\n"
        "- Do NOT restart/stop/recreate any containers or services.\n"
        "- Do NOT deploy, update images, run apt-get, or change configuration files.\n"
        "- Do NOT prune/remove volumes/images/containers.\n"
        "- Only run read-only diagnostics (docker ps/inspect/logs/stats, curl, df, free, uptime, etc.).\n"
        "- If you believe a restart would help, suggest it as a human action but do not execute it.\n"
    )


def _build_host_health_dispatch_prompt(*, violations: list[str], snap: dict[str, Any]) -> str:
    snap_json = json.dumps(snap, indent=2, ensure_ascii=False, sort_keys=True)
    violations_txt = "\n".join(f"- {v}" for v in violations[:20]) if violations else "(none)"
    return (
        "The production service-monitoring detected host health threshold violations (e.g. high CPU/RAM/disk usage).\n\n"
        f"Observed violations:\n{violations_txt}\n\n"
        "Host snapshot (JSON):\n"
        f"{snap_json}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm whether disk/memory/swap/cpu/load is actually under pressure on the production host.\n"
        "2) Identify top resource consumers (especially Docker containers).\n"
        "3) Gather evidence: docker ps, docker stats --no-stream, docker inspect (limits), df -h, df -i, free -m, uptime.\n"
        "4) Explain the most likely root cause(s) and the safest remediation steps for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- Root cause hypothesis + evidence\n"
        "- What is consuming resources (container names, sizes, cpu/mem)\n"
        "- Immediate safe actions (non-disruptive) + next steps\n"
    )


def _build_performance_dispatch_prompt(*, slow: list[dict[str, Any]]) -> str:
    entries = slow[:20]
    slow_lines = []
    for e in entries:
        domain = e.get("domain")
        http_ms = _format_ms(e.get("http_ms"))
        browser_ms = _format_ms(e.get("browser_ms"))
        reasons = e.get("reasons") or []
        reason_txt = ", ".join(str(x) for x in reasons[:4]) if reasons else "slow"
        slow_lines.append(f"- {domain}: HTTP {http_ms}, Browser {browser_ms} ({reason_txt})")
    slow_txt = "\n".join(slow_lines) if slow_lines else "(none)"
    return (
        "The production service-monitoring container detected consistently slow response times for monitored domains.\n\n"
        "Slow domains:\n"
        f"{slow_txt}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce timings from the production host with curl (include DNS/TLS/connect/TTFB/total breakdown).\n"
        "2) Check whether slowness is isolated to one domain or systemic (DNS, outbound network, CPU pressure).\n"
        "3) If the slow domain is reverse-proxied on the host, inspect the relevant proxy/container logs and health.\n"
        "4) Provide a clear triage summary and recommended next actions for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- Reproduction results (commands + timings)\n"
        "- Most likely root cause + evidence\n"
        "- Impacted domains and whether it's systemic\n"
        "- Recommended safe remediation steps (no changes executed)\n"
    )


def _build_tls_alert_message(
    *,
    results: list[TlsCertCheckResult],
    min_days_valid: float,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    bad = [r for r in results if not r.ok]
    lines = ["Monitor warning: TLS certificate checks are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append(f"Threshold: min_days_valid={float(min_days_valid):.1f}d")
    lines.append("")
    for r in bad[:15]:
        host = r.host or "?"
        port = r.port or 443
        days = "n/a" if r.days_remaining is None else f"{r.days_remaining:.2f}d"
        err = (r.error or "unknown").strip()
        lines.append(f"- {r.domain}: {err} host={host}:{port} days_remaining={days} not_after={r.not_after_iso}")
    return "\n".join(lines).strip()


def _build_tls_dispatch_prompt(*, results: list[TlsCertCheckResult], min_days_valid: float) -> str:
    bad = [r for r in results if not r.ok]
    payload = [
        {
            "domain": r.domain,
            "host": r.host,
            "port": r.port,
            "not_after_iso": r.not_after_iso,
            "days_remaining": r.days_remaining,
            "error": r.error,
            "details": r.details,
        }
        for r in bad[:20]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected TLS certificate problems (expiry soon / handshake failures).\n\n"
        f"Threshold: min_days_valid={float(min_days_valid):.1f} days\n\n"
        "Failing TLS checks (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm certificate status from the production host with openssl s_client / curl -Iv.\n"
        "2) If expiry is near, check certbot/Let's Encrypt renewal status and Nginx config for the affected domain.\n"
        "3) Identify whether the issue is DNS/SNI mismatch, expired cert, wrong cert installed, or renewal failure.\n"
        "4) Provide a clear remediation plan for a human operator (avoid making changes).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Affected domains + expiry dates\n"
        "- Recommended safe remediation steps\n"
    )


def _build_dns_alert_message(
    *,
    results: list[DnsCheckResult],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    bad = [r for r in results if not r.ok]
    lines = ["Monitor warning: DNS checks are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for r in bad[:15]:
        a = ",".join(r.a_records[:4]) if r.a_records else "-"
        aaaa = ",".join(r.aaaa_records[:4]) if r.aaaa_records else "-"
        drift = " drift" if r.drift_detected else ""
        exp = ",".join((r.expected_ips or [])[:4]) if r.expected_ips else "-"
        err = (r.error or "").strip()
        extra = f" error={err}" if err else ""
        lines.append(f"- {r.domain}:{drift} A=[{a}] AAAA=[{aaaa}] expected=[{exp}]{extra}")
    return "\n".join(lines).strip()


def _build_dns_dispatch_prompt(*, results: list[DnsCheckResult]) -> str:
    bad = [r for r in results if not r.ok]
    payload = [
        {
            "domain": r.domain,
            "a_records": r.a_records,
            "aaaa_records": r.aaaa_records,
            "drift_detected": r.drift_detected,
            "expected_ips": r.expected_ips,
            "error": r.error,
        }
        for r in bad[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected DNS resolution problems (NXDOMAIN/timeout/no A/AAAA or drift).\n\n"
        "Failing DNS checks (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm DNS resolution from the production host using dig/host/nslookup against multiple resolvers.\n"
        "2) Determine whether the issue is authoritative DNS, resolver, DNSSEC, or transient network.\n"
        "3) If drift is flagged, assess whether the change is expected (deploy/failover) or suspicious.\n"
        "4) Provide a human-safe remediation plan (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Affected domains + observed records\n"
        "- Recommended safe remediation steps\n"
    )


def _build_slo_alert_message(
    *,
    violations: list[SloBurnViolation],
    slo_target_percent: float,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: SLO error budget burn rate is high ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append(f"SLO target: {float(slo_target_percent):.3f}%")
    lines.append("")
    for v in violations[:15]:
        s_av = "n/a" if v.short_availability_percent is None else f"{v.short_availability_percent:.3f}%"
        l_av = "n/a" if v.long_availability_percent is None else f"{v.long_availability_percent:.3f}%"
        lines.append(
            f"- {v.domain}: rule={v.rule} burn={v.short_burn_rate:.2f}/{v.long_burn_rate:.2f} "
            f"avail={s_av}/{l_av} samples={v.short_total}/{v.long_total} "
            f"windows={v.short_window_minutes}m/{v.long_window_minutes}m"
        )
    return "\n".join(lines).strip()


def _build_slo_dispatch_prompt(*, violations: list[SloBurnViolation], slo_target_percent: float) -> str:
    payload = [
        {
            "domain": v.domain,
            "rule": v.rule,
            "short_window_minutes": v.short_window_minutes,
            "long_window_minutes": v.long_window_minutes,
            "short_burn_rate": v.short_burn_rate,
            "long_burn_rate": v.long_burn_rate,
            "short_availability_percent": v.short_availability_percent,
            "long_availability_percent": v.long_availability_percent,
            "short_total": v.short_total,
            "long_total": v.long_total,
        }
        for v in violations[:30]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected high error-budget burn rate (SLO at risk).\n\n"
        f"SLO target: {float(slo_target_percent):.3f}%\n\n"
        "Triggered burn-rate violations (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Identify which domains/services are causing burn-rate violations and whether issues are ongoing.\n"
        "2) Correlate with recent deploys, container restarts/OOMs, Nginx upstream errors, and host resource pressure.\n"
        "3) Provide a clear summary of likely root cause(s) and recommended next steps for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- What is burning budget + since when\n"
        "- Root cause hypothesis + evidence\n"
        "- Recommended safe remediation steps\n"
    )


def _build_red_alert_message(
    *,
    violations: list[RedViolation],
    window_minutes: int,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: RED / golden-signal checks are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append(f"Window: {int(window_minutes)}m")
    lines.append("")
    for v in violations[:15]:
        err = "n/a" if v.error_rate_percent is None else f"{v.error_rate_percent:.2f}%"
        http_p95 = "n/a" if v.http_p95_ms is None else f"{int(round(v.http_p95_ms))}ms"
        br_p95 = "n/a" if v.browser_p95_ms is None else f"{int(round(v.browser_p95_ms))}ms"
        reasons = ",".join(v.reasons[:4]) if v.reasons else "degraded"
        lines.append(f"- {v.domain}: {reasons} err={err} http_p95={http_p95} browser_p95={br_p95} samples={v.total_samples}")
    return "\n".join(lines).strip()


def _build_red_dispatch_prompt(*, violations: list[RedViolation], window_minutes: int) -> str:
    payload = [
        {
            "domain": v.domain,
            "reasons": v.reasons,
            "total_samples": v.total_samples,
            "error_rate_percent": v.error_rate_percent,
            "http_p95_ms": v.http_p95_ms,
            "browser_p95_ms": v.browser_p95_ms,
        }
        for v in violations[:30]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected degraded RED/golden signals (error-rate and/or latency percentiles).\n\n"
        f"Window: {int(window_minutes)} minutes\n\n"
        "Violations (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce latency and errors from the production host (curl timings; check DNS/TLS/connect/TTFB/total).\n"
        "2) Determine whether the issue is isolated to one service or systemic (host load, network, DNS).\n"
        "3) Check container status/restarts and relevant logs for the impacted services.\n"
        "4) Provide a triage summary and recommended next steps for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- Reproduction results\n"
        "- Root cause hypothesis + evidence\n"
        "- Recommended safe remediation steps\n"
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


def _build_synthetic_alert_message(
    *,
    failures: list[SyntheticTransactionResult],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: Synthetic transactions are failing ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for r in failures[:15]:
        ms = "n/a" if r.elapsed_ms is None else f"{int(round(float(r.elapsed_ms)))}ms"
        err = (r.error or "transaction_failed").strip()[:260]
        url = (r.details or {}).get("final_url")
        lines.append(f"- {r.domain} [{r.name}]: {err} ({ms}) url={url}")
    return "\n".join(lines).strip()


def _build_synthetic_dispatch_prompt(*, failures: list[SyntheticTransactionResult]) -> str:
    payload = [
        {
            "domain": r.domain,
            "name": r.name,
            "elapsed_ms": r.elapsed_ms,
            "error": r.error,
            "details": r.details,
            "browser_infra_error": r.browser_infra_error,
        }
        for r in failures[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected synthetic end-to-end transaction failures (Playwright step flows).\n\n"
        "Failures (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce the failing transaction(s) from the production host (Playwright or curl where possible).\n"
        "2) Determine whether the failure is frontend regression, backend/API failure, reverse proxy issue, or auth flow change.\n"
        "3) Inspect relevant containers and logs.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Impacted domains/transactions\n"
        "- Recommended safe remediation steps\n"
    )


def _build_web_vitals_alert_message(
    *,
    failures: list[WebVitalsResult],
    thresholds: dict[str, float | None],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: Core Web Vitals are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    th = ", ".join(f"{k}={v}" for k, v in thresholds.items() if v is not None)
    if th:
        lines.append(f"Thresholds: {th}")
    lines.append("")
    for r in failures[:15]:
        m = r.metrics or {}
        lcp = m.get("lcp_ms")
        cls = m.get("cls")
        inp = m.get("inp_ms")
        err = (r.error or "").strip()[:260]
        parts = []
        if lcp is not None:
            parts.append(f"LCP={int(round(float(lcp)))}ms")
        if cls is not None:
            parts.append(f"CLS={float(cls):.3f}")
        if inp is not None:
            parts.append(f"INP~={int(round(float(inp)))}ms")
        vit = " ".join(parts) if parts else "metrics=n/a"
        extra = f" error={err}" if err else ""
        lines.append(f"- {r.domain}: {vit}{extra}")
    return "\n".join(lines).strip()


def _build_web_vitals_dispatch_prompt(*, failures: list[WebVitalsResult]) -> str:
    payload = [
        {
            "domain": r.domain,
            "metrics": r.metrics,
            "error": r.error,
            "elapsed_ms": r.elapsed_ms,
            "browser_infra_error": r.browser_infra_error,
        }
        for r in failures[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected degraded Core Web Vitals (LCP/CLS/INP approximation).\n\n"
        "Failures (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm the vitals with Lighthouse / Chrome DevTools (from the production host) for affected domains.\n"
        "2) Identify likely causes (slow backend/TTFB, oversized assets, render-blocking JS/CSS, layout shifts).\n"
        "3) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Most likely cause + evidence\n"
        "- Impacted domains\n"
        "- Recommended safe remediation steps\n"
    )


def _build_container_health_alert_message(
    *,
    issues: list[ContainerHealthIssue],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: Docker container health is degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for it in issues[:15]:
        parts = []
        if it.running is False:
            parts.append("NOT_RUNNING")
        if it.health_status and it.health_status != "healthy":
            parts.append(f"health={it.health_status}")
        if it.oom_killed:
            parts.append("OOMKilled")
        if it.restart_increase is not None and it.restart_increase > 0:
            parts.append(f"restarted(+{it.restart_increase})")
        if it.exit_code is not None and it.exit_code != 0:
            parts.append(f"exit={it.exit_code}")
        if it.error:
            parts.append(f"error={it.error}")
        flags = ",".join(parts) if parts else "issue"
        lines.append(f"- {it.name} ({it.container_id}): {flags} status={it.status}")
    return "\n".join(lines).strip()


def _build_container_health_dispatch_prompt(*, issues: list[ContainerHealthIssue]) -> str:
    payload = [
        {
            "name": it.name,
            "container_id": it.container_id,
            "running": it.running,
            "status": it.status,
            "restart_count": it.restart_count,
            "restart_increase": it.restart_increase,
            "oom_killed": it.oom_killed,
            "health_status": it.health_status,
            "exit_code": it.exit_code,
            "error": it.error,
        }
        for it in issues[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected Docker container health issues (unhealthy/not running/restarting/OOM).\n\n"
        "Issues (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm container states with docker ps/inspect, and check recent restarts/OOMKilled.\n"
        "2) Gather logs for the affected containers (docker logs --tail 200).\n"
        "3) Correlate with host resource pressure (df/free/uptime) and recent deploys.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Affected containers + status\n"
        "- Recommended safe remediation steps\n"
    )


def _build_proxy_alert_message(
    *,
    upstream_issues: list[ProxyIssue],
    access_stats: NginxAccessWindowStats | None,
    upstream_errors_summary: dict[str, Any] | None,
    window_seconds: int,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: Reverse proxy / upstream signals are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append(f"Window: {int(window_seconds)}s")
    lines.append("")

    if upstream_issues:
        lines.append("Upstream header issues:")
        for it in upstream_issues[:12]:
            lines.append(f"- {it.domain}: {it.reason} {it.header}={it.value}")
        lines.append("")

    if access_stats is not None:
        total = int(access_stats.total)
        rate_502 = 0.0
        if total > 0:
            rate_502 = (int(access_stats.status_502_504) / float(total)) * 100.0
        lines.append(
            f"Nginx access: total={total} 5xx={access_stats.status_5xx} 502/504={access_stats.status_502_504} ({rate_502:.2f}%)"
        )
        if access_stats.sample_lines:
            lines.append("Sample 502/504 lines:")
            lines.extend(f"- {ln}" for ln in access_stats.sample_lines[:6])
        lines.append("")

    if upstream_errors_summary and isinstance(upstream_errors_summary.get("counts_by_server"), dict):
        lines.append("Nginx upstream errors (error.log):")
        counts = upstream_errors_summary.get("counts_by_server") or {}
        for server, count in sorted(counts.items(), key=lambda kv: int(kv[1]), reverse=True)[:10]:
            lines.append(f"- {server}: {int(count)}")
        lines.append("")

    return "\n".join(lines).strip()


def _build_proxy_dispatch_prompt(
    *,
    upstream_issues: list[ProxyIssue],
    access_stats: NginxAccessWindowStats | None,
    upstream_error_events: list[NginxUpstreamErrorEvent],
    window_seconds: int,
) -> str:
    payload = {
        "window_seconds": int(window_seconds),
        "upstream_header_issues": [
            {
                "domain": it.domain,
                "reason": it.reason,
                "header": it.header,
                "value": it.value,
                "details": it.details,
            }
            for it in upstream_issues[:25]
        ],
        "nginx_access": (
            {
                "total": access_stats.total,
                "status_5xx": access_stats.status_5xx,
                "status_502_504": access_stats.status_502_504,
                "status_4xx": access_stats.status_4xx,
                "sample_lines": access_stats.sample_lines[:8],
            }
            if access_stats is not None
            else None
        ),
        "nginx_upstream_errors": [
            {"ts": e.ts, "level": e.level, "server": e.server, "upstream": e.upstream, "message": e.message}
            for e in upstream_error_events[:60]
        ],
    }
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected reverse proxy upstream/failover issues (backup upstream, 502/504 spike, or upstream errors).\n\n"
        "Details (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm Nginx upstream status on the production host (curl -i to affected domains; inspect upstream headers).\n"
        "2) Check Nginx error.log for upstream failures and correlate to service containers/ports.\n"
        "3) Identify which upstream (primary/backup) is serving and why failover occurred.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Impacted domains/upstreams\n"
        "- Recommended safe remediation steps\n"
    )


def _build_meta_alert_message(
    *,
    reasons: list[str],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    lines = ["Monitor warning: monitoring pipeline is degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for r in reasons[:12]:
        lines.append(f"- {r}")
    return "\n".join(lines).strip()


def _build_meta_dispatch_prompt(*, reasons: list[str], context: dict[str, Any]) -> str:
    details = json.dumps({"reasons": reasons[:25], "context": context}, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected that the monitoring pipeline itself is degraded (cycle overruns/state write failures/etc.).\n\n"
        "Details (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm whether the service-monitoring container is overloaded (CPU/mem), or stuck (slow cycles).\n"
        "2) Check host resource pressure and docker stats.\n"
        "3) Check monitor container logs for repeated errors (state write, Telegram, Playwright launch).\n"
        "4) Provide a safe remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause hypothesis + evidence\n"
        "- Impact (are we missing checks/alerts?)\n"
        "- Recommended safe remediation steps\n"
    )


async def _dispatch_prompt_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    prompt: str,
    state_key: str,
    telegram_title: str,
    dispatch_state: dict[str, Any],
) -> None:
    if not _dispatch_is_enabled(dispatch_cfg, dispatch_state):
        LOGGER.info("Dispatch disabled; skipping dispatch title=%s", telegram_title)
        return

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
        LOGGER.info("Dispatch queued title=%s bundle=%s runner=%s", telegram_title, bundle, runner)

        await wait_for_terminal_status(http_client, dispatch_cfg, bundle=bundle)
        ui = run_ui_url(dispatch_cfg.base_url, bundle)
        tail = await get_run_log_tail(http_client, dispatch_cfg, bundle=bundle)
        msg = extract_last_agent_message_from_exec_log(tail) or await get_last_agent_message(
            http_client, dispatch_cfg, bundle=bundle
        )
        if not msg:
            err = extract_last_error_message_from_exec_log(tail) or ""
            err_txt = err.strip()
            err_l = err_txt.lower()

            # Disable dispatch on runner quota/billing errors to avoid spamming and wasting cycles.
            if "quota exceeded" in err_l or "billing details" in err_l or "insufficient_quota" in err_l:
                _dispatch_disable(dispatch_state, reason="runner_quota_exceeded", cooldown_seconds=None)
                if _dispatch_should_notify(dispatch_state, min_interval_seconds=3600.0):
                    await _notify_dispatch_disabled(
                        http_client=http_client,
                        telegram_cfg=telegram_cfg,
                        dispatch_state=dispatch_state,
                        details=f"Dispatcher runner quota exceeded. Update PITCHAI_DISPATCH_TOKEN secret and redeploy. {ui}",
                    )
                LOGGER.warning(
                    "Dispatch disabled due to runner quota title=%s bundle=%s error=%s",
                    telegram_title,
                    bundle,
                    err_txt[:500] if err_txt else None,
                )
                return

            extra = f" Last error: {err_txt[:300]}" if err_txt else ""
            ok, resp = await send_telegram_message(
                http_client,
                telegram_cfg,
                f"{telegram_title} finished (bundle={bundle}) but no agent message was found.{extra} {ui}",
            )
            LOGGER.warning(
                "Dispatch finished no_message title=%s bundle=%s sent_ok=%s telegram=%s",
                telegram_title,
                bundle,
                ok,
                redact_telegram_response(resp),
            )
            return

        header = f"{telegram_title} (bundle={bundle})\n{ui}\n\n"
        ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, header + msg)
        LOGGER.info(
            "Dispatch finished title=%s bundle=%s telegram_ok=%s telegram_last=%s",
            telegram_title,
            bundle,
            ok_all,
            redact_telegram_response(resps[-1] if resps else {}),
        )
    except httpx.HTTPStatusError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        err = f"HTTPStatusError: {exc}"
        suppress_notice = False

        # Disable dispatch on auth/quota issues to avoid spamming and wasting cycles.
        if status_code in {401, 403}:
            _dispatch_disable(dispatch_state, reason=f"auth_error_{status_code}", cooldown_seconds=None)
            suppress_notice = True
            if _dispatch_should_notify(dispatch_state, min_interval_seconds=3600.0):
                await _notify_dispatch_disabled(
                    http_client=http_client,
                    telegram_cfg=telegram_cfg,
                    dispatch_state=dispatch_state,
                    details=f"Dispatcher returned {status_code}. Update PITCHAI_DISPATCH_TOKEN secret and redeploy.",
                )
        elif status_code == 429:
            _dispatch_disable(dispatch_state, reason="rate_limited_429", cooldown_seconds=30 * 60)
            suppress_notice = True
            if _dispatch_should_notify(dispatch_state, min_interval_seconds=1800.0):
                await _notify_dispatch_disabled(
                    http_client=http_client,
                    telegram_cfg=telegram_cfg,
                    dispatch_state=dispatch_state,
                    details="Dispatcher rate-limited (429). Will retry automatically after cooldown.",
                )

        LOGGER.exception("Dispatch failed title=%s status_code=%s error=%s", telegram_title, status_code, err)
        if not suppress_notice:
            await send_telegram_message(
                http_client,
                telegram_cfg,
                f"{telegram_title} dispatch escalation FAILED: {err}",
            )
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("Dispatch failed title=%s error=%s", telegram_title, err)
        await send_telegram_message(
            http_client,
            telegram_cfg,
            f"{telegram_title} dispatch escalation FAILED: {err}",
        )


async def _dispatch_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    result: DomainCheckResult,
    dispatch_state: dict[str, Any],
) -> None:
    prompt = _build_dispatch_prompt(result)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key=f"service-monitoring.{result.domain}",
        telegram_title=f"{result.domain} investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_host_health_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    violations: list[str],
    snap: dict[str, Any],
) -> None:
    prompt = _build_host_health_dispatch_prompt(violations=violations, snap=snap)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.host_health",
        telegram_title="Host health investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_performance_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    slow: list[dict[str, Any]],
) -> None:
    prompt = _build_performance_dispatch_prompt(slow=slow)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.performance",
        telegram_title="Performance investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_tls_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    results: list[TlsCertCheckResult],
    min_days_valid: float,
) -> None:
    prompt = _build_tls_dispatch_prompt(results=results, min_days_valid=min_days_valid)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.tls",
        telegram_title="TLS investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_dns_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    results: list[DnsCheckResult],
) -> None:
    prompt = _build_dns_dispatch_prompt(results=results)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.dns",
        telegram_title="DNS investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_slo_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    violations: list[SloBurnViolation],
    slo_target_percent: float,
) -> None:
    prompt = _build_slo_dispatch_prompt(violations=violations, slo_target_percent=slo_target_percent)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.slo",
        telegram_title="SLO burn investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_red_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    violations: list[RedViolation],
    window_minutes: int,
) -> None:
    prompt = _build_red_dispatch_prompt(violations=violations, window_minutes=window_minutes)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.red",
        telegram_title="RED signals investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_api_contract_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    failures: list[ApiContractCheckResult],
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
    )


async def _dispatch_synthetic_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    failures: list[SyntheticTransactionResult],
) -> None:
    prompt = _build_synthetic_dispatch_prompt(failures=failures)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.synthetic",
        telegram_title="Synthetic transactions investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_web_vitals_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    failures: list[WebVitalsResult],
) -> None:
    prompt = _build_web_vitals_dispatch_prompt(failures=failures)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.web_vitals",
        telegram_title="Web vitals investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_container_health_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    issues: list[ContainerHealthIssue],
) -> None:
    prompt = _build_container_health_dispatch_prompt(issues=issues)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.container_health",
        telegram_title="Container health investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_proxy_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    upstream_issues: list[ProxyIssue],
    access_stats: NginxAccessWindowStats | None,
    upstream_error_events: list[NginxUpstreamErrorEvent],
    window_seconds: int,
) -> None:
    prompt = _build_proxy_dispatch_prompt(
        upstream_issues=upstream_issues,
        access_stats=access_stats,
        upstream_error_events=upstream_error_events,
        window_seconds=window_seconds,
    )
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.proxy",
        telegram_title="Proxy/upstream investigation",
        dispatch_state=dispatch_state,
    )


async def _dispatch_meta_and_forward(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    dispatch_cfg: DispatchConfig,
    dispatch_state: dict[str, Any],
    reasons: list[str],
    context: dict[str, Any],
) -> None:
    prompt = _build_meta_dispatch_prompt(reasons=reasons, context=context)
    await _dispatch_prompt_and_forward(
        http_client=http_client,
        telegram_cfg=telegram_cfg,
        dispatch_cfg=dispatch_cfg,
        prompt=prompt,
        state_key="service-monitoring.meta",
        telegram_title="Monitoring pipeline investigation",
        dispatch_state=dispatch_state,
    )


async def check_one_domain(
    spec: DomainCheckSpec,
    http_client: httpx.AsyncClient,
    browser: Browser | None,
    *,
    browser_semaphore: asyncio.Semaphore,
) -> DomainCheckResult:
    http_ok, http_details = await http_get_check(spec, http_client)
    if not http_ok:
        return DomainCheckResult(
            domain=spec.domain,
            ok=False,
            reason="http_check_failed",
            details=http_details,
        )

    if browser is None:
        return DomainCheckResult(
            domain=spec.domain,
            ok=True,
            reason="browser_degraded",
            details={
                **http_details,
                "error": "browser_unavailable",
                "browser_connected": False,
                "browser_infra_error": True,
                "browser_elapsed_ms": None,
            },
        )

    async with browser_semaphore:
        browser_ok, browser_details = await browser_check(spec, browser)
    if not browser_ok:
        if bool(browser_details.get("browser_infra_error")):
            return DomainCheckResult(
                domain=spec.domain,
                ok=True,
                reason="browser_degraded",
                details={**http_details, **browser_details},
            )
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
    tolerance_seconds = max(120, interval_seconds * 2)
    browser_concurrency = max(1, int(config.get("browser_concurrency", 3)))
    check_concurrency = max(1, int(config.get("check_concurrency", 25)))
    alerting_cfg = config.get("alerting") or {}
    if not isinstance(alerting_cfg, dict):
        alerting_cfg = {}
    down_after_failures = max(1, int(alerting_cfg.get("down_after_failures", 1)))
    up_after_successes = max(1, int(alerting_cfg.get("up_after_successes", 1)))

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
    specs_by_domain: dict[str, DomainCheckSpec] = {
        entry.domain: load_domain_spec(entry.raw_entry) for entry in domain_entries
    }
    all_domains = [entry.domain for entry in domain_entries]

    heartbeat_cfg = _get_heartbeat_config(config)
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

    host_health_cfg = _get_host_health_config(config)
    host_health_enabled = bool(host_health_cfg.get("enabled", False))
    host_health_down_after_failures = max(1, int(host_health_cfg.get("down_after_failures", 1)))
    host_health_up_after_successes = max(1, int(host_health_cfg.get("up_after_successes", 1)))
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

    perf_cfg = _get_performance_config(config)
    perf_enabled = bool(perf_cfg.get("enabled", False))
    perf_down_after_failures = max(1, int(perf_cfg.get("down_after_failures", 1)))
    perf_up_after_successes = max(1, int(perf_cfg.get("up_after_successes", 1)))
    perf_http_elapsed_ms_max = _coerce_float(perf_cfg.get("http_elapsed_ms_max", 1500.0), default=1500.0)
    perf_browser_elapsed_ms_max = _coerce_float(perf_cfg.get("browser_elapsed_ms_max", 4000.0), default=4000.0)
    perf_dispatch_on_degraded = bool(perf_cfg.get("dispatch_on_degraded", False))
    perf_notify_on_recovery = bool(perf_cfg.get("notify_on_recovery", False))
    perf_overrides = None
    overrides_raw = perf_cfg.get("per_domain_overrides")
    if isinstance(overrides_raw, dict):
        perf_overrides = overrides_raw

    history_cfg = _get_history_config(config)
    history_retention_days = _coerce_float(history_cfg.get("retention_days", 7.0), default=7.0)
    history_retention_days = max(1.0, float(history_retention_days))
    history_retention_seconds = history_retention_days * 86400.0

    slo_cfg = _get_slo_config(config)
    slo_enabled = bool(slo_cfg.get("enabled", False))
    slo_target_percent = _coerce_float(slo_cfg.get("target_percent", 99.9), default=99.9)
    slo_down_after_failures = max(1, int(slo_cfg.get("down_after_failures", 3)))
    slo_up_after_successes = max(1, int(slo_cfg.get("up_after_successes", 2)))
    slo_dispatch_on_degraded = bool(slo_cfg.get("dispatch_on_degraded", False))
    slo_notify_on_recovery = bool(slo_cfg.get("notify_on_recovery", False))
    slo_min_total_samples = max(1, int(slo_cfg.get("min_total_samples", 5)))
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

    tls_cfg = _get_tls_config(config)
    tls_enabled = bool(tls_cfg.get("enabled", False))
    tls_interval_minutes = max(1, int(tls_cfg.get("interval_minutes", 60)))
    tls_min_days_valid = _coerce_float(tls_cfg.get("min_days_valid", 14.0), default=14.0)
    tls_timeout_seconds = _coerce_float(tls_cfg.get("timeout_seconds", 8.0), default=8.0)
    tls_down_after_failures = max(1, int(tls_cfg.get("down_after_failures", 2)))
    tls_up_after_successes = max(1, int(tls_cfg.get("up_after_successes", 1)))
    tls_dispatch_on_degraded = bool(tls_cfg.get("dispatch_on_degraded", False))
    tls_notify_on_recovery = bool(tls_cfg.get("notify_on_recovery", False))

    dns_cfg = _get_dns_config(config)
    dns_enabled = bool(dns_cfg.get("enabled", False))
    dns_interval_minutes = max(1, int(dns_cfg.get("interval_minutes", 15)))
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
    dns_down_after_failures = max(1, int(dns_cfg.get("down_after_failures", 2)))
    dns_up_after_successes = max(1, int(dns_cfg.get("up_after_successes", 1)))
    dns_dispatch_on_degraded = bool(dns_cfg.get("dispatch_on_degraded", False))
    dns_notify_on_recovery = bool(dns_cfg.get("notify_on_recovery", False))

    red_cfg = _get_red_config(config)
    red_enabled = bool(red_cfg.get("enabled", False))
    red_window_minutes = max(1, int(red_cfg.get("window_minutes", 30)))
    red_min_samples = max(1, int(red_cfg.get("min_samples", 10)))
    red_error_rate_max_percent = _coerce_optional_float(red_cfg.get("error_rate_max_percent"))
    red_http_p95_ms_max = _coerce_optional_float(red_cfg.get("http_p95_ms_max"))
    red_browser_p95_ms_max = _coerce_optional_float(red_cfg.get("browser_p95_ms_max"))
    red_down_after_failures = max(1, int(red_cfg.get("down_after_failures", 3)))
    red_up_after_successes = max(1, int(red_cfg.get("up_after_successes", 2)))
    red_dispatch_on_degraded = bool(red_cfg.get("dispatch_on_degraded", False))
    red_notify_on_recovery = bool(red_cfg.get("notify_on_recovery", False))

    syn_cfg = _get_synthetic_config(config)
    syn_enabled = bool(syn_cfg.get("enabled", False))
    syn_interval_minutes = max(1, int(syn_cfg.get("interval_minutes", 15)))
    syn_max_domains_per_cycle = max(1, int(syn_cfg.get("max_domains_per_cycle", 1)))
    syn_timeout_seconds = _coerce_float(syn_cfg.get("timeout_seconds", 35.0), default=35.0)
    syn_down_after_failures = max(1, int(syn_cfg.get("down_after_failures", 2)))
    syn_up_after_successes = max(1, int(syn_cfg.get("up_after_successes", 2)))
    syn_dispatch_on_degraded = bool(syn_cfg.get("dispatch_on_degraded", False))
    syn_notify_on_recovery = bool(syn_cfg.get("notify_on_recovery", False))

    wv_cfg = _get_web_vitals_config(config)
    wv_enabled = bool(wv_cfg.get("enabled", False))
    wv_interval_minutes = max(1, int(wv_cfg.get("interval_minutes", 60)))
    wv_max_domains_per_cycle = max(1, int(wv_cfg.get("max_domains_per_cycle", 1)))
    wv_timeout_seconds = _coerce_float(wv_cfg.get("timeout_seconds", 45.0), default=45.0)
    wv_post_load_wait_ms = _coerce_int(wv_cfg.get("post_load_wait_ms", 4500), default=4500)
    wv_lcp_ms_max = _coerce_optional_float(wv_cfg.get("lcp_ms_max"))
    wv_cls_max = _coerce_optional_float(wv_cfg.get("cls_max"))
    wv_inp_ms_max = _coerce_optional_float(wv_cfg.get("inp_ms_max"))
    wv_down_after_failures = max(1, int(wv_cfg.get("down_after_failures", 2)))
    wv_up_after_successes = max(1, int(wv_cfg.get("up_after_successes", 2)))
    wv_dispatch_on_degraded = bool(wv_cfg.get("dispatch_on_degraded", False))
    wv_notify_on_recovery = bool(wv_cfg.get("notify_on_recovery", False))

    api_cfg = _get_api_contract_config(config)
    api_enabled = bool(api_cfg.get("enabled", False))
    api_interval_minutes = max(1, int(api_cfg.get("interval_minutes", 10)))
    api_timeout_seconds = _coerce_float(api_cfg.get("timeout_seconds", 10.0), default=10.0)
    api_down_after_failures = max(1, int(api_cfg.get("down_after_failures", 2)))
    api_up_after_successes = max(1, int(api_cfg.get("up_after_successes", 2)))
    api_dispatch_on_degraded = bool(api_cfg.get("dispatch_on_degraded", False))
    api_notify_on_recovery = bool(api_cfg.get("notify_on_recovery", False))

    container_cfg = _get_container_health_config(config)
    container_enabled = bool(container_cfg.get("enabled", False))
    container_interval_minutes = max(1, int(container_cfg.get("interval_minutes", 1)))
    docker_socket_path = str(container_cfg.get("docker_socket_path") or "/var/run/docker.sock").strip()
    container_monitor_all = bool(container_cfg.get("monitor_all", False))
    container_include_patterns = container_cfg.get("include_name_patterns") if isinstance(container_cfg.get("include_name_patterns"), list) else []
    container_exclude_patterns = container_cfg.get("exclude_name_patterns") if isinstance(container_cfg.get("exclude_name_patterns"), list) else []
    container_timeout_seconds = _coerce_float(container_cfg.get("timeout_seconds", 3.0), default=3.0)
    container_down_after_failures = max(1, int(container_cfg.get("down_after_failures", 2)))
    container_up_after_successes = max(1, int(container_cfg.get("up_after_successes", 1)))
    container_dispatch_on_degraded = bool(container_cfg.get("dispatch_on_degraded", False))
    container_notify_on_recovery = bool(container_cfg.get("notify_on_recovery", False))

    proxy_cfg = _get_proxy_config(config)
    proxy_enabled = bool(proxy_cfg.get("enabled", False))
    proxy_access_log_path = str(proxy_cfg.get("access_log_path") or "/var/log/nginx/access.log").strip()
    proxy_error_log_path = str(proxy_cfg.get("error_log_path") or "/var/log/nginx/error.log").strip()
    proxy_timezone_name = str(proxy_cfg.get("timezone") or "Europe/Amsterdam").strip() or "Europe/Amsterdam"
    proxy_window_seconds = max(60, int(proxy_cfg.get("window_seconds", 300)))
    proxy_access_max_bytes = max(10_000, int(proxy_cfg.get("access_log_max_bytes", 1_000_000)))
    proxy_error_max_bytes = max(10_000, int(proxy_cfg.get("error_log_max_bytes", 1_000_000)))
    proxy_min_total_requests = max(0, int(proxy_cfg.get("min_total_requests", 50)))
    proxy_max_502_504_percent = _coerce_optional_float(proxy_cfg.get("max_502_504_percent"))
    proxy_max_upstream_errors_per_domain = max(0, int(proxy_cfg.get("max_upstream_errors_per_domain", 5)))
    proxy_down_after_failures = max(1, int(proxy_cfg.get("down_after_failures", 2)))
    proxy_up_after_successes = max(1, int(proxy_cfg.get("up_after_successes", 2)))
    proxy_dispatch_on_degraded = bool(proxy_cfg.get("dispatch_on_degraded", False))
    proxy_notify_on_recovery = bool(proxy_cfg.get("notify_on_recovery", False))

    meta_cfg = _get_meta_monitoring_config(config)
    meta_enabled = bool(meta_cfg.get("enabled", False))
    meta_cycle_overrun_factor = _coerce_float(meta_cfg.get("cycle_overrun_factor", 1.25), default=1.25)
    meta_state_write_failures_max = max(1, int(meta_cfg.get("state_write_failures_max", 3)))
    meta_down_after_failures = max(1, int(meta_cfg.get("down_after_failures", 2)))
    meta_up_after_successes = max(1, int(meta_cfg.get("up_after_successes", 2)))
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
    if state_path is not None:
        disk_state = _load_monitor_state(state_path)
        last_ok.update(disk_state.get("last_ok") or {})
        fail_streak.update(disk_state.get("fail_streak") or {})
        success_streak.update(disk_state.get("success_streak") or {})
        history_by_domain = disk_state.get("history") or {}
        host_state = disk_state.get("host_health")
        if isinstance(host_state, dict):
            host_health_last_ok = _coerce_bool(host_state.get("last_ok"), default=True)
            host_health_fail_streak = _coerce_int(host_state.get("fail_streak"), default=0)
            host_health_success_streak = _coerce_int(host_state.get("success_streak"), default=0)
            host_cpu_prev_total = _coerce_int(host_state.get("cpu_prev_total"), default=0)
            host_cpu_prev_idle = _coerce_int(host_state.get("cpu_prev_idle"), default=0)
        perf_state = disk_state.get("performance")
        if isinstance(perf_state, dict):
            perf_last_ok = _coerce_bool(perf_state.get("last_ok"), default=True)
            perf_fail_streak = _coerce_int(perf_state.get("fail_streak"), default=0)
            perf_success_streak = _coerce_int(perf_state.get("success_streak"), default=0)
        slo_state = disk_state.get("slo")
        if isinstance(slo_state, dict):
            slo_last_ok = _coerce_bool(slo_state.get("last_ok"), default=True)
            slo_fail_streak = _coerce_int(slo_state.get("fail_streak"), default=0)
            slo_success_streak = _coerce_int(slo_state.get("success_streak"), default=0)

        tls_state = disk_state.get("tls")
        if isinstance(tls_state, dict):
            tls_last_ok = _coerce_bool(tls_state.get("last_ok"), default=True)
            tls_fail_streak = _coerce_int(tls_state.get("fail_streak"), default=0)
            tls_success_streak = _coerce_int(tls_state.get("success_streak"), default=0)
            tls_last_run_ts = _coerce_float(tls_state.get("last_run_ts"), default=0.0)

        dns_state = disk_state.get("dns")
        if isinstance(dns_state, dict):
            dns_last_ok = _coerce_bool(dns_state.get("last_ok"), default=True)
            dns_fail_streak = _coerce_int(dns_state.get("fail_streak"), default=0)
            dns_success_streak = _coerce_int(dns_state.get("success_streak"), default=0)
            dns_last_run_ts = _coerce_float(dns_state.get("last_run_ts"), default=0.0)
            dns_last_ips = _coerce_str_list_dict(dns_state.get("last_ips"))

        red_state = disk_state.get("red")
        if isinstance(red_state, dict):
            red_last_ok = _coerce_bool(red_state.get("last_ok"), default=True)
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
            container_last_ok = _coerce_bool(cont_state.get("last_ok"), default=True)
            container_fail_streak = _coerce_int(cont_state.get("fail_streak"), default=0)
            container_success_streak = _coerce_int(cont_state.get("success_streak"), default=0)
            container_last_run_ts = _coerce_float(cont_state.get("last_run_ts"), default=0.0)
            container_restart_counts = _coerce_int_dict(cont_state.get("restart_counts"))

        proxy_state = disk_state.get("proxy")
        if isinstance(proxy_state, dict):
            proxy_last_ok = _coerce_bool(proxy_state.get("last_ok"), default=True)
            proxy_fail_streak = _coerce_int(proxy_state.get("fail_streak"), default=0)
            proxy_success_streak = _coerce_int(proxy_state.get("success_streak"), default=0)

        meta_state = disk_state.get("meta")
        if isinstance(meta_state, dict):
            meta_last_ok = _coerce_bool(meta_state.get("last_ok"), default=True)
            meta_fail_streak = _coerce_int(meta_state.get("fail_streak"), default=0)
            meta_success_streak = _coerce_int(meta_state.get("success_streak"), default=0)
            state_write_fail_streak = _coerce_int(meta_state.get("state_write_fail_streak"), default=0)
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
        "browser_degraded_active": False,
        "browser_degraded_first_seen_ts": 0.0,
        "browser_degraded_last_notice_ts": float(disk_state.get("browser_degraded_last_notice_ts") or 0.0),
        "browser_degraded_recover_streak": 0,
        "browser_degraded_notice_min_interval_seconds": 6 * 3600,
        "browser_launch_fail_count": 0,
        "browser_launch_next_try_ts": 0.0,
        "browser_launch_last_error": None,
        "browser_min_mem_available_mb": max(0, browser_min_mem_available_mb),
    }

    def _build_state_payload() -> dict[str, Any]:
        return {
            "version": 4,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_ok": last_ok,
            "fail_streak": fail_streak,
            "success_streak": success_streak,
            "history": history_by_domain,
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

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as http_client:
        async with async_playwright() as p:
            browser: Browser | None = None

            async def _launch_browser() -> Browser:
                args = [
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-features=site-per-process",
                ]

                shm_bytes = 0
                try:
                    st = os.statvfs("/dev/shm")
                    shm_bytes = int(st.f_frsize) * int(st.f_blocks)
                except Exception:
                    shm_bytes = 0
                if shm_bytes < (512 * 1024 * 1024):
                    # CI defaults to a tiny /dev/shm; this avoids renderer crashes when shared memory is constrained.
                    args.insert(1, "--disable-dev-shm-usage")

                launch_kwargs: dict[str, Any] = {"headless": True, "args": args}
                if chromium_path:
                    launch_kwargs["executable_path"] = chromium_path
                return await p.chromium.launch(**launch_kwargs)

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

                        if alerted_down:
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
                            ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                            resp = resps[-1] if resps else {}
                            LOGGER.warning(
                                "Alert attempt domain=%s sent_ok=%s reason=%s telegram=%s details=%s",
                                domain,
                                ok_all,
                                result.reason,
                                redact_telegram_response(resp),
                                enriched.details,
                            )

                            if dispatch_cfg and _dispatch_is_enabled(dispatch_cfg, dispatch_state):
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
                                        )
                                    )
                            else:
                                LOGGER.info(
                                    "Dispatch not scheduled domain=%s enabled=%s reason=%s",
                                    domain,
                                    bool(dispatch_cfg and dispatch_state.get("enabled")),
                                    dispatch_state.get("disabled_reason"),
                                )
                        else:
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

                        append_sample(
                            history_by_domain,
                            domain=domain,
                            ts=float(cycle_started),
                            ok=bool(result.ok),
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

                        if slo_alerted_down and slo_violations:
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
                                        )
                                    )

                        slo_recovered = (not prev_effective) and bool(slo_last_ok)
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

                        if red_alerted_down and red_violations:
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
                                        )
                                    )

                        red_recovered = (not prev_effective) and bool(red_last_ok)
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

                        if host_alerted_down and host_violations:
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
                                        )
                                    )

                        host_recovered = (not prev_effective) and bool(host_health_last_ok)
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

                        if perf_alerted_down and perf_slow:
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
                                        )
                                    )

                        perf_recovered = (not prev_effective) and bool(perf_last_ok)
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

                            tls_observed_ok = all(r.ok for r in (tls_results or []))
                            prev_effective = bool(tls_last_ok)
                            tls_last_ok, tls_fail_streak, tls_success_streak, tls_alerted_down = _update_effective_ok(
                                prev_effective_ok=prev_effective,
                                observed_ok=tls_observed_ok,
                                fail_streak=int(tls_fail_streak),
                                success_streak=int(tls_success_streak),
                                down_after_failures=tls_down_after_failures,
                                up_after_successes=tls_up_after_successes,
                            )

                            if tls_alerted_down and tls_results and (not tls_observed_ok):
                                msg = _build_tls_alert_message(
                                    results=tls_results,
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
                                                results=tls_results,
                                                min_days_valid=float(tls_min_days_valid),
                                            )
                                        )

                            tls_recovered = (not prev_effective) and bool(tls_last_ok)
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

                            dns_observed_ok = all(r.ok for r in (dns_results or []))
                            prev_effective = bool(dns_last_ok)
                            dns_last_ok, dns_fail_streak, dns_success_streak, dns_alerted_down = _update_effective_ok(
                                prev_effective_ok=prev_effective,
                                observed_ok=dns_observed_ok,
                                fail_streak=int(dns_fail_streak),
                                success_streak=int(dns_success_streak),
                                down_after_failures=dns_down_after_failures,
                                up_after_successes=dns_up_after_successes,
                            )

                            if dns_alerted_down and dns_results and (not dns_observed_ok):
                                msg = _build_dns_alert_message(
                                    results=dns_results,
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
                                                results=dns_results,
                                            )
                                        )

                            dns_recovered = (not prev_effective) and bool(dns_last_ok)
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
                                    failures = [r for r in results if not r.ok]
                                    api_failures_to_alert.extend(failures)
                                    api_failures_for_dispatch.extend(failures)
                                    msg = _build_api_contract_alert_message(
                                        failures=failures,
                                        down_after_failures=api_down_after_failures,
                                        fail_streak=int(next_fail),
                                    )
                                    ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                                    LOGGER.warning(
                                        "API contract degraded domain=%s sent_ok=%s telegram_last=%s",
                                        domain,
                                        ok_all,
                                        redact_telegram_response(resps[-1] if resps else {}),
                                    )
                                else:
                                    if (not prev_effective) and bool(next_effective) and api_notify_on_recovery:
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

                            if container_alerted_down and container_issues:
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
                                            )
                                        )

                            container_recovered = (not prev_effective) and bool(container_last_ok)
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
                        upstream_issues = check_upstream_header_expectations(
                            specs_by_domain=specs_by_domain, cycle_results=cycle_results
                        )

                        access_stats = None
                        access_violation = False
                        if proxy_max_502_504_percent is not None and proxy_access_log_path:
                            access_stats = compute_access_window_stats(
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
                            upstream_events = parse_recent_upstream_errors(
                                error_log_path=proxy_error_log_path,
                                now=datetime.now(timezone.utc),
                                window_seconds=int(proxy_window_seconds),
                                local_tz=proxy_tz,
                                max_bytes=int(proxy_error_max_bytes),
                            )
                            upstream_summary = summarize_upstream_errors(upstream_events)
                            counts = upstream_summary.get("counts_by_server") if isinstance(upstream_summary, dict) else {}
                            if isinstance(counts, dict):
                                enabled_domains = {s.domain for s in enabled_specs}
                                for server, count in counts.items():
                                    if server not in enabled_domains:
                                        continue
                                    if int(count) >= int(proxy_max_upstream_errors_per_domain):
                                        upstream_violation = True
                                        break

                        proxy_observed_ok = (not upstream_issues) and (not access_violation) and (not upstream_violation)
                        prev_effective = bool(proxy_last_ok)
                        proxy_last_ok, proxy_fail_streak, proxy_success_streak, proxy_alerted_down = _update_effective_ok(
                            prev_effective_ok=prev_effective,
                            observed_ok=proxy_observed_ok,
                            fail_streak=int(proxy_fail_streak),
                            success_streak=int(proxy_success_streak),
                            down_after_failures=proxy_down_after_failures,
                            up_after_successes=proxy_up_after_successes,
                        )

                        if proxy_alerted_down and (not proxy_observed_ok):
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
                                        )
                                    )

                        proxy_recovered = (not prev_effective) and bool(proxy_last_ok)
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
                                msg = _build_synthetic_alert_message(
                                    failures=real_failures,
                                    down_after_failures=syn_down_after_failures,
                                    fail_streak=int(next_fail),
                                )
                                ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                                LOGGER.warning(
                                    "Synthetic degraded domain=%s sent_ok=%s telegram_last=%s",
                                    spec.domain,
                                    ok_all,
                                    redact_telegram_response(resps[-1] if resps else {}),
                                )
                                syn_failures_for_dispatch.extend(real_failures)
                            else:
                                recovered = (not prev_effective) and bool(next_effective)
                                if recovered and syn_notify_on_recovery:
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
                                msg = _build_web_vitals_alert_message(
                                    failures=[evaluated],
                                    thresholds=thresholds,
                                    down_after_failures=wv_down_after_failures,
                                    fail_streak=int(next_fail),
                                )
                                ok_all, resps = await send_telegram_message_chunked(http_client, telegram_cfg, msg)
                                LOGGER.warning(
                                    "Web vitals degraded domain=%s sent_ok=%s telegram_last=%s",
                                    spec.domain,
                                    ok_all,
                                    redact_telegram_response(resps[-1] if resps else {}),
                                )
                                wv_failures_for_dispatch.append(evaluated)
                            else:
                                recovered = (not prev_effective) and bool(next_effective)
                                if recovered and wv_notify_on_recovery:
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
                                    )
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
                                msg = _build_heartbeat_message(
                                    now=now,
                                    scheduled_label=f"{hhmm} {heartbeat_timezone}",
                                    started_at=started_at,
                                    results=cycle_results,
                                    disabled_lines=disabled_lines,
                                    host_snap=host_snap,
                                    host_violations=host_violations,
                                    perf_slow=perf_slow if perf_enabled else None,
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

                        if meta_alerted_down and meta_reasons:
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
                                        )
                                    )

                        meta_recovered = (not prev_effective) and bool(meta_last_ok)
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

                    sleep_for = max(0.0, interval_seconds - elapsed)
                    LOGGER.info(
                        "Cycle complete elapsed_seconds=%s sleep_seconds=%s",
                        round(elapsed, 3),
                        round(sleep_for, 3),
                    )
                    await asyncio.sleep(sleep_for)
            finally:
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
