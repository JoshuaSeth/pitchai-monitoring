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


@dataclass(frozen=True)
class RegistrySettings:
    db_path: str = field(default_factory=lambda: os.getenv("E2E_REGISTRY_DB_PATH", "/data/e2e-registry.db"))
    artifacts_dir: str = field(default_factory=lambda: os.getenv("E2E_ARTIFACTS_DIR", "/data/e2e-artifacts"))

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
