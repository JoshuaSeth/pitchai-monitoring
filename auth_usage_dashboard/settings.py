# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validate authentication usage dashboard environment settings."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    msg = f"{name} must be a boolean"
    raise RuntimeError(msg)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw.strip())
    except ValueError as exc:
        msg = f"{name} must be an integer"
        raise RuntimeError(msg) from exc
    if not minimum <= value <= maximum:
        msg = f"{name} must be between {minimum} and {maximum}"
        raise RuntimeError(msg)
    return value


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw.strip())
    except ValueError as exc:
        msg = f"{name} must be a number"
        raise RuntimeError(msg) from exc
    if not minimum <= value <= maximum:
        msg = f"{name} must be between {minimum} and {maximum}"
        raise RuntimeError(msg)
    return value


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class DashboardSettings(NamedTuple):
    """Represent validated immutable dashboard configuration."""

    broker_data_dir: Path
    broker_url: str
    broker_admin_token: str
    bind_host: str = "127.0.0.1"
    bind_port: int = 8124
    snapshot_refresh_seconds: int = 15
    safe_probe_interval_seconds: int = 300
    analytics_probe_interval_seconds: int = 900
    manual_probe_min_interval_seconds: int = 60
    stale_after_seconds: int = 600
    analytics_stale_after_seconds: int = 1800
    request_timeout_seconds: float = 25.0
    min_five_hour_remaining_percent: float = 10.0
    safe_probe_enabled: bool = True
    probe_on_startup: bool = True
    require_proxy_auth: bool = True
    proxy_auth_header: str = "x-pitchai-email"
    history_file: Path | None = None
    history_retention_days: int = 8
    history_sample_interval_seconds: int = 300

    def with_history_file(self, history_file: Path) -> DashboardSettings:
        """Return an immutable copy using one explicit sample-history path."""
        return DashboardSettings(
            broker_data_dir=self.broker_data_dir,
            broker_url=self.broker_url,
            broker_admin_token=self.broker_admin_token,
            bind_host=self.bind_host,
            bind_port=self.bind_port,
            snapshot_refresh_seconds=self.snapshot_refresh_seconds,
            safe_probe_interval_seconds=self.safe_probe_interval_seconds,
            analytics_probe_interval_seconds=self.analytics_probe_interval_seconds,
            manual_probe_min_interval_seconds=self.manual_probe_min_interval_seconds,
            stale_after_seconds=self.stale_after_seconds,
            analytics_stale_after_seconds=self.analytics_stale_after_seconds,
            request_timeout_seconds=self.request_timeout_seconds,
            min_five_hour_remaining_percent=self.min_five_hour_remaining_percent,
            safe_probe_enabled=self.safe_probe_enabled,
            probe_on_startup=self.probe_on_startup,
            require_proxy_auth=self.require_proxy_auth,
            proxy_auth_header=self.proxy_auth_header,
            history_file=history_file,
            history_retention_days=self.history_retention_days,
            history_sample_interval_seconds=self.history_sample_interval_seconds,
        )

    @classmethod
    def from_env(cls) -> DashboardSettings:
        """Build from env.

        Returns:
            The resulting value.

        Raises:
            RuntimeError: If the operation cannot satisfy its runtime contract.

        """
        broker_url = os.getenv("AUTH_USAGE_BROKER_URL", "http://127.0.0.1:38188").strip().rstrip("/")
        parsed = urlsplit(broker_url)
        allow_remote = _env_bool("AUTH_USAGE_ALLOW_REMOTE_BROKER", default=False)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            msg = "AUTH_USAGE_BROKER_URL must be an absolute HTTP(S) URL"
            raise RuntimeError(msg)
        if not allow_remote and not _is_loopback_host(parsed.hostname):
            msg = "AUTH_USAGE_BROKER_URL must be loopback unless AUTH_USAGE_ALLOW_REMOTE_BROKER=1"
            raise RuntimeError(msg)

        bind_host = os.getenv("AUTH_USAGE_BIND_HOST", "127.0.0.1").strip()
        public_bind = _env_bool("AUTH_USAGE_ALLOW_PUBLIC_BIND", default=False)
        if not public_bind and not _is_loopback_host(bind_host):
            msg = "AUTH_USAGE_BIND_HOST must be loopback unless AUTH_USAGE_ALLOW_PUBLIC_BIND=1"
            raise RuntimeError(msg)

        safe_probe_enabled = _env_bool("AUTH_USAGE_SAFE_PROBE_ENABLED", default=True)
        admin_token = (
            os.getenv("AUTH_USAGE_BROKER_ADMIN_TOKEN") or os.getenv("AUTH_TOKEN_SERVER_ADMIN_TOKEN") or ""
        ).strip()
        if safe_probe_enabled and not admin_token:
            msg = "AUTH_USAGE_BROKER_ADMIN_TOKEN or AUTH_TOKEN_SERVER_ADMIN_TOKEN is required"
            raise RuntimeError(msg)

        return cls(
            broker_data_dir=Path(
                os.getenv("AUTH_USAGE_BROKER_DATA_DIR", "/broker-data"),
            ).expanduser(),
            broker_url=broker_url,
            broker_admin_token=admin_token,
            bind_host=bind_host,
            bind_port=_env_int(
                "AUTH_USAGE_BIND_PORT",
                8124,
                minimum=1024,
                maximum=65535,
            ),
            snapshot_refresh_seconds=_env_int(
                "AUTH_USAGE_SNAPSHOT_REFRESH_SECONDS",
                15,
                minimum=5,
                maximum=300,
            ),
            safe_probe_interval_seconds=_env_int(
                "AUTH_USAGE_SAFE_PROBE_INTERVAL_SECONDS",
                300,
                minimum=60,
                maximum=3600,
            ),
            analytics_probe_interval_seconds=_env_int(
                "AUTH_USAGE_ANALYTICS_PROBE_INTERVAL_SECONDS",
                900,
                minimum=300,
                maximum=86400,
            ),
            manual_probe_min_interval_seconds=_env_int(
                "AUTH_USAGE_MANUAL_PROBE_MIN_INTERVAL_SECONDS",
                60,
                minimum=30,
                maximum=900,
            ),
            stale_after_seconds=_env_int(
                "AUTH_USAGE_STALE_AFTER_SECONDS",
                600,
                minimum=120,
                maximum=86400,
            ),
            analytics_stale_after_seconds=_env_int(
                "AUTH_USAGE_ANALYTICS_STALE_AFTER_SECONDS",
                1800,
                minimum=600,
                maximum=172800,
            ),
            request_timeout_seconds=_env_float(
                "AUTH_USAGE_REQUEST_TIMEOUT_SECONDS",
                25.0,
                minimum=2.0,
                maximum=120.0,
            ),
            min_five_hour_remaining_percent=_env_float(
                "AUTH_TOKEN_SERVER_MIN_FIVE_HOUR_REMAINING_PERCENT",
                10.0,
                minimum=0.0,
                maximum=100.0,
            ),
            safe_probe_enabled=safe_probe_enabled,
            probe_on_startup=_env_bool("AUTH_USAGE_PROBE_ON_STARTUP", default=True),
            require_proxy_auth=_env_bool("AUTH_USAGE_REQUIRE_PROXY_AUTH", default=True),
            proxy_auth_header=os
            .getenv(
                "AUTH_USAGE_PROXY_AUTH_HEADER",
                "x-pitchai-email",
            )
            .strip()
            .lower(),
            history_file=Path(
                os.getenv(
                    "AUTH_USAGE_HISTORY_FILE",
                    "/dashboard-data/usage-samples.json",
                ),
            ).expanduser(),
            history_retention_days=_env_int(
                "AUTH_USAGE_HISTORY_RETENTION_DAYS",
                8,
                minimum=7,
                maximum=31,
            ),
            history_sample_interval_seconds=_env_int(
                "AUTH_USAGE_HISTORY_SAMPLE_INTERVAL_SECONDS",
                300,
                minimum=60,
                maximum=1800,
            ),
        )
