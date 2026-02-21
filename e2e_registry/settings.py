from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    s = str(raw).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return str(default)
    s = str(raw).strip()
    return s if s else str(default)


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return ()
    out: list[str] = []
    for part in str(raw).split(","):
        item = part.strip().lower()
        if item:
            out.append(item)
    return tuple(out)


def _strict_base_url_policy_default() -> bool:
    raw = os.getenv("E2E_REGISTRY_STRICT_BASE_URL_POLICY")
    if raw is not None:
        return _env_bool("E2E_REGISTRY_STRICT_BASE_URL_POLICY", False)
    public = str(os.getenv("E2E_REGISTRY_PUBLIC_BASE_URL", "")).strip().lower()
    return "monitoring.pitchai.net" in public


@dataclass(frozen=True)
class RegistrySettings:
    db_path: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_DB_PATH", "/data/e2e-registry.db"))
    artifacts_dir: str = field(default_factory=lambda: os.getenv("E2E_ARTIFACTS_DIR", "/data/e2e-artifacts"))
    tests_dir: str = field(default_factory=lambda: os.getenv("E2E_TESTS_DIR", "/data/e2e-tests"))

    # Admin token is used only for admin endpoints (create tenant/api keys).
    admin_token: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_ADMIN_TOKEN", ""))
    # Monitor token is used only for read-only status endpoints (e.g. heartbeats).
    monitor_token: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_MONITOR_TOKEN", ""))
    # Runner token is required for runner claim/complete endpoints.
    runner_token: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_RUNNER_TOKEN", ""))

    # Alerting
    alerts_enabled: bool = field(default_factory=lambda: _env_bool("E2E_REGISTRY_ALERTS_ENABLED", True))
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("E2E_TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    )
    telegram_chat_id: str = field(
        default_factory=lambda: os.getenv("E2E_TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")
    )

    # Optional Dispatcher escalation on test failures (read-only rules).
    dispatch_enabled: bool = field(default_factory=lambda: _env_bool("E2E_REGISTRY_DISPATCH_ENABLED", False))
    dispatch_base_url: str = field(
        default_factory=lambda: os.getenv("PITCHAI_DISPATCH_BASE_URL", "https://dispatch.pitchai.net").strip()
    )
    dispatch_token: str = field(default_factory=lambda: os.getenv("PITCHAI_DISPATCH_TOKEN", "").strip())
    dispatch_model: str = field(default_factory=lambda: os.getenv("PITCHAI_DISPATCH_MODEL", "").strip())

    # Used to build stable links in Telegram messages.
    public_base_url: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_PUBLIC_BASE_URL", "").strip())

    # Scheduling/locking.
    runner_lock_timeout_seconds: int = field(
        default_factory=lambda: _env_int("E2E_REGISTRY_RUNNER_LOCK_TIMEOUT_SECONDS", 10 * 60)
    )

    # Upload guardrails.
    max_upload_bytes: int = field(default_factory=lambda: _env_int("E2E_REGISTRY_MAX_UPLOAD_BYTES", 512_000))
    strict_base_url_policy: bool = field(default_factory=_strict_base_url_policy_default)
    # Optional explicit allowlist for strict mode (comma-separated hostnames).
    base_url_allowed_hosts: tuple[str, ...] = field(default_factory=lambda: _env_csv("E2E_REGISTRY_ALLOWED_BASE_URL_HOSTS"))
    # If strict mode and explicit allowlist is empty, derive allowlist from monitoring config domains.
    base_url_allow_monitored_domains: bool = field(default_factory=lambda: _env_bool("E2E_REGISTRY_ALLOW_MONITORED_DOMAINS", True))

    # --- Monitoring dashboard (served by the same web app on monitoring.pitchai.net) ---
    # Path to the service-monitoring state.json volume (mounted read-only into this container).
    monitor_state_path: str = field(default_factory=lambda: _env_str("SERVICE_MONITOR_STATE_PATH", "/monitor_state/state.json"))
    # Path to the monitoring config yaml (baked into the image by default).
    monitor_config_path: str = field(default_factory=lambda: _env_str("SERVICE_MONITOR_CONFIG_PATH", "/app/domain_checks/config.yaml"))
    # Require a monitoring/admin token login to view the dashboard.
    dashboard_require_auth: bool = field(default_factory=lambda: _env_bool("MONITOR_DASHBOARD_REQUIRE_AUTH", True))
    # How many points to return per timeseries (downsamples server-side).
    dashboard_max_points: int = field(default_factory=lambda: _env_int("MONITOR_DASHBOARD_MAX_POINTS", 1500))
