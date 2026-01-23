from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import runpy
import time
from datetime import datetime, timedelta, time as dt_time, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from playwright.async_api import async_playwright
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


def _build_heartbeat_message(
    *,
    now: datetime,
    scheduled_label: str,
    started_at: datetime,
    results: dict[str, DomainCheckResult],
) -> str:
    lines = [
        "Heartbeat: service-monitoring is running ✅",
        f"Scheduled: {scheduled_label}",
        f"Now: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Uptime: {_format_uptime(now - started_at)}",
        "",
        "Domains (HTTP / Browser):",
    ]

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


def _load_monitor_state(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"last_ok": {}, "fail_streak": {}, "success_streak": {}}
    except Exception as exc:
        LOGGER.warning("Failed to read state file path=%s error=%s", path, exc)
        return {"last_ok": {}, "fail_streak": {}, "success_streak": {}}

    if not isinstance(raw, dict):
        return {"last_ok": {}, "fail_streak": {}, "success_streak": {}}

    # Back-compat: previously stored only {"last_ok": {...}} or raw mapping.
    if isinstance(raw.get("last_ok"), dict) and not any(k in raw for k in ("fail_streak", "success_streak")):
        return {
            "last_ok": _coerce_bool_dict(raw.get("last_ok")),
            "fail_streak": {},
            "success_streak": {},
        }

    if all(isinstance(v, bool) for v in raw.values()):
        return {
            "last_ok": _coerce_bool_dict(raw),
            "fail_streak": {},
            "success_streak": {},
        }

    return {
        "last_ok": _coerce_bool_dict(raw.get("last_ok")),
        "fail_streak": _coerce_int_dict(raw.get("fail_streak")),
        "success_streak": _coerce_int_dict(raw.get("success_streak")),
    }


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
    dispatch_state: dict[str, Any],
) -> None:
    if not _dispatch_is_enabled(dispatch_cfg, dispatch_state):
        LOGGER.info("Dispatch disabled; skipping dispatch for domain=%s", result.domain)
        return

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
    except httpx.HTTPStatusError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        err = f"HTTPStatusError: {exc}"
        suppress_domain_notice = False

        # Disable dispatch on auth/quota issues to avoid spamming and wasting cycles.
        if status_code in {401, 403}:
            _dispatch_disable(dispatch_state, reason=f"auth_error_{status_code}", cooldown_seconds=None)
            suppress_domain_notice = True
            if _dispatch_should_notify(dispatch_state, min_interval_seconds=3600.0):
                await _notify_dispatch_disabled(
                    http_client=http_client,
                    telegram_cfg=telegram_cfg,
                    dispatch_state=dispatch_state,
                    details=f"Dispatcher returned {status_code}. Update PITCHAI_DISPATCH_TOKEN secret and redeploy.",
                )
        elif status_code == 429:
            _dispatch_disable(dispatch_state, reason="rate_limited_429", cooldown_seconds=30 * 60)
            suppress_domain_notice = True
            if _dispatch_should_notify(dispatch_state, min_interval_seconds=1800.0):
                await _notify_dispatch_disabled(
                    http_client=http_client,
                    telegram_cfg=telegram_cfg,
                    dispatch_state=dispatch_state,
                    details="Dispatcher rate-limited (429). Will retry automatically after cooldown.",
                )

        LOGGER.exception("Dispatch failed domain=%s status_code=%s error=%s", result.domain, status_code, err)
        if not suppress_domain_notice:
            await send_telegram_message(
                http_client,
                telegram_cfg,
                f"{result.domain} dispatch escalation FAILED: {err}",
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

    specs: list[DomainCheckSpec] = [load_domain_spec(entry) for entry in domains_cfg]

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

    chromium_path = find_chromium_executable()
    if not chromium_path:
        raise RuntimeError("Could not find a Chromium/Chrome executable (set CHROMIUM_PATH)")

    LOGGER.info(
        "Starting service monitor domains=%s interval_seconds=%s chromium_path=%s",
        [s.domain for s in specs],
        interval_seconds,
        chromium_path,
    )

    state_path_raw = str(os.getenv("STATE_PATH", "/data/state.json") or "").strip()
    state_path = Path(state_path_raw) if state_path_raw else None

    # Track state (persisted if STATE_PATH is mounted) to avoid spamming alerts every minute.
    last_ok: dict[str, bool] = {}
    fail_streak: dict[str, int] = {}
    success_streak: dict[str, int] = {}
    if state_path is not None:
        disk_state = _load_monitor_state(state_path)
        last_ok.update(disk_state.get("last_ok") or {})
        fail_streak.update(disk_state.get("fail_streak") or {})
        success_streak.update(disk_state.get("success_streak") or {})
    active_dispatch_tasks: dict[str, asyncio.Task[None]] = {}
    browser_semaphore = asyncio.Semaphore(browser_concurrency)
    monitor_state: dict[str, Any] = {"last_browser_degraded_notify_monotonic": 0.0}

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as http_client:
        async with async_playwright() as p:
            async def _launch_browser():
                return await p.chromium.launch(
                    headless=True,
                    executable_path=chromium_path,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )

            browser = await _launch_browser()
            try:
                while True:
                    cycle_started = time.time()
                    cycle_results: dict[str, DomainCheckResult] = {}
                    LOGGER.info("Running check cycle")

                    browser_degraded = False

                    async def _safe_check(spec: DomainCheckSpec) -> DomainCheckResult:
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

                    tasks = [asyncio.create_task(_safe_check(spec)) for spec in specs]

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

                    if browser_degraded:
                        now_mono = time.monotonic()
                        last_notice = float(monitor_state.get("last_browser_degraded_notify_monotonic") or 0.0)
                        if (now_mono - last_notice) >= 600.0:
                            monitor_state["last_browser_degraded_notify_monotonic"] = now_mono
                            await send_telegram_message(
                                http_client,
                                telegram_cfg,
                                "Monitor warning: Playwright browser checks are degraded (browser crash/close detected). "
                                "Continuing with HTTP-only results and restarting the browser process.",
                            )

                        try:
                            await browser.close()
                        except Exception:
                            pass
                        browser = await _launch_browser()

                    # Prune completed dispatch tasks to avoid unbounded growth.
                    for domain, task in list(active_dispatch_tasks.items()):
                        if not task.done():
                            continue
                        try:
                            task.result()
                        except Exception:
                            LOGGER.exception("Dispatch task crashed domain=%s", domain)
                        del active_dispatch_tasks[domain]

                    if heartbeat_enabled and cycle_results:
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
                                    "version": 2,
                                    "updated_at": datetime.now(timezone.utc).isoformat(),
                                    "last_ok": last_ok,
                                    "fail_streak": fail_streak,
                                    "success_streak": success_streak,
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
