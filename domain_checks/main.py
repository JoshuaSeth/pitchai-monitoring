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

    for idx, entry in enumerate(domains_cfg):
        if isinstance(entry, str):
            domain = entry.strip()
            if not domain:
                raise ValueError(f"domains[{idx}] is empty")
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
        "Task:\n"
        f"1) Investigate why {result.domain} is not functioning properly on the production host.\n"
        "2) Use Docker to identify the relevant service container(s) and reverse proxy (by name/image/labels/ports).\n"
        "3) Inspect container status, recent restarts, health checks, and logs.\n"
        "4) Check for common root causes: upstream crash-loop, bad deploy, DNS, cert expiry, proxy config, "
        "resource exhaustion, and disk space issues.\n"
        "5) If a fix is safe and targeted (only the relevant service), apply the minimal fix (e.g., restart that "
        "one container) and re-check.\n"
        "6) If a fix is risky (and not straightforward to instantly revert if it turned out bad) or could disrupt other services, do NOT apply it—just explain clearly.\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Actions taken (if any) + commands run\n"
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
    disk_state: dict[str, Any] = {}
    host_health_last_ok = True
    host_health_fail_streak = 0
    host_health_success_streak = 0
    host_cpu_prev_total = 0
    host_cpu_prev_idle = 0
    perf_last_ok = True
    perf_fail_streak = 0
    perf_success_streak = 0
    if state_path is not None:
        disk_state = _load_monitor_state(state_path)
        last_ok.update(disk_state.get("last_ok") or {})
        fail_streak.update(disk_state.get("fail_streak") or {})
        success_streak.update(disk_state.get("success_streak") or {})
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
                                    _write_state_atomic(
                                        state_path,
                                        {
                                            "version": 3,
                                            "updated_at": datetime.now(timezone.utc).isoformat(),
                                            "last_ok": last_ok,
                                            "fail_streak": fail_streak,
                                            "success_streak": success_streak,
                                            "browser_degraded_last_notice_ts": float(
                                                monitor_state.get("browser_degraded_last_notice_ts") or 0.0
                                            ),
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
                                        },
                                    )
                                except Exception as exc:
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
                            _write_state_atomic(
                                state_path,
                                {
                                    "version": 3,
                                    "updated_at": datetime.now(timezone.utc).isoformat(),
                                    "last_ok": last_ok,
                                    "fail_streak": fail_streak,
                                    "success_streak": success_streak,
                                    "browser_degraded_last_notice_ts": float(
                                        monitor_state.get("browser_degraded_last_notice_ts") or 0.0
                                    ),
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
                                },
                            )
                        except Exception as exc:
                            LOGGER.warning("Failed to write state file path=%s error=%s", state_path, exc)

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
