# Copyright (c) 2026 PitchAI. All rights reserved.
"""Environment-backed E2E registry service settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, *, default: bool) -> bool:
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
    except ValueError:
        return int(default)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return str(default)
    s = str(raw).strip()
    return s or str(default)


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
        return _env_bool("E2E_REGISTRY_STRICT_BASE_URL_POLICY", default=False)
    public = str(os.getenv("E2E_REGISTRY_PUBLIC_BASE_URL", "")).strip().lower()
    return "monitoring.pitchai.net" in public


@dataclass(frozen=True)
class _StorageSettings:
    """Persistent storage and upload limits."""

    db_path: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_DB_PATH", "/data/e2e-registry.db"))
    artifacts_dir: str = field(default_factory=lambda: os.getenv("E2E_ARTIFACTS_DIR", "/data/e2e-artifacts"))
    tests_dir: str = field(default_factory=lambda: os.getenv("E2E_TESTS_DIR", "/data/e2e-tests"))
    max_upload_bytes: int = field(default_factory=lambda: _env_int("E2E_REGISTRY_MAX_UPLOAD_BYTES", 512_000))


@dataclass(frozen=True)
class _AuthenticationSettings:
    """Bearer tokens and trusted dashboard identity configuration."""

    # Admin token is used only for admin endpoints (create tenant/api keys).
    admin_token: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_ADMIN_TOKEN", ""))
    # Monitor token is used only for read-only status endpoints (e.g. heartbeats).
    monitor_token: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_MONITOR_TOKEN", ""))
    # Runner token is required for runner claim/complete endpoints.
    runner_token: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_RUNNER_TOKEN", ""))
    dashboard_identity_header: str = field(
        default_factory=lambda: _env_str("MONITOR_DASHBOARD_IDENTITY_HEADER", "x-pitchai-email").lower(),
    )


@dataclass(frozen=True)
class _TelegramSettings:
    """Telegram failure-notification configuration."""

    alerts_enabled: bool = field(
        default_factory=lambda: _env_bool("E2E_REGISTRY_ALERTS_ENABLED", default=True),
    )
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("E2E_TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", ""),
    )
    telegram_chat_id: str = field(
        default_factory=lambda: os.getenv("E2E_TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", ""),
    )


@dataclass(frozen=True)
class _DispatchSettings:
    """Optional Dispatcher failure-escalation configuration."""

    dispatch_enabled: bool = field(
        default_factory=lambda: _env_bool("E2E_REGISTRY_DISPATCH_ENABLED", default=False),
    )
    dispatch_base_url: str = field(
        default_factory=lambda: os.getenv("PITCHAI_DISPATCH_BASE_URL", "https://dispatch.pitchai.net").strip(),
    )
    dispatch_token: str = field(default_factory=lambda: os.getenv("PITCHAI_DISPATCH_TOKEN", "").strip())
    dispatch_model: str = field(default_factory=lambda: os.getenv("PITCHAI_DISPATCH_MODEL", "").strip())
    public_base_url: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_PUBLIC_BASE_URL", "").strip())


@dataclass(frozen=True)
class _RunnerPolicySettings:
    """Scheduling and strict browser-target policy."""

    runner_lock_timeout_seconds: int = field(
        default_factory=lambda: _env_int("E2E_REGISTRY_RUNNER_LOCK_TIMEOUT_SECONDS", 10 * 60),
    )
    strict_base_url_policy: bool = field(default_factory=_strict_base_url_policy_default)
    base_url_allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: _env_csv("E2E_REGISTRY_ALLOWED_BASE_URL_HOSTS"),
    )
    base_url_allow_monitored_domains: bool = field(
        default_factory=lambda: _env_bool("E2E_REGISTRY_ALLOW_MONITORED_DOMAINS", default=True),
    )


@dataclass(frozen=True)
class _MonitoringSettings:
    """Read-only monitoring dashboard inputs and response bounds."""

    monitor_state_path: str = field(
        default_factory=lambda: _env_str("SERVICE_MONITOR_STATE_PATH", "/monitor_state/state.json"),
    )
    monitor_config_path: str = field(
        default_factory=lambda: _env_str("SERVICE_MONITOR_CONFIG_PATH", "/app/domain_checks/config.yaml"),
    )
    dashboard_max_points: int = field(default_factory=lambda: _env_int("MONITOR_DASHBOARD_MAX_POINTS", 1500))


@dataclass(frozen=True)
class RegistrySettings(
    _StorageSettings,
    _AuthenticationSettings,
    _TelegramSettings,
    _DispatchSettings,
    _RunnerPolicySettings,
    _MonitoringSettings,
):
    """Complete E2E registry configuration resolved at construction time."""
