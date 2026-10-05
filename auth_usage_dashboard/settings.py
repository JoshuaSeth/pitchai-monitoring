# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validated, loopback-by-default environment configuration of the capacity dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .settings_environment import environment_flag, environment_integer, environment_number, is_loopback_host


@dataclass(frozen=True)
class _BrokerEndpointSettings:
    """Where the redacted broker state lives and where the dashboard listens."""

    broker_data_dir: Path
    broker_url: str
    broker_admin_token: str
    bind_host: str = "127.0.0.1"
    bind_port: int = 8124


@dataclass(frozen=True)
class _RefreshCadenceSettings:
    """Snapshot refresh, probe, staleness, and broker request timing."""

    snapshot_refresh_seconds: int = 15
    safe_probe_interval_seconds: int = 300
    analytics_probe_interval_seconds: int = 900
    manual_probe_min_interval_seconds: int = 60
    stale_after_seconds: int = 600
    analytics_stale_after_seconds: int = 1800
    request_timeout_seconds: float = 25.0


@dataclass(frozen=True)
class _ProbeAccessSettings:
    """Routing floor, safe-probe switches, and the trusted proxy identity header."""

    min_five_hour_remaining_percent: float = 10.0
    safe_probe_enabled: bool = True
    probe_on_startup: bool = True
    require_proxy_auth: bool = True
    proxy_auth_header: str = "x-pitchai-email"


@dataclass(frozen=True)
class DashboardSettings(_ProbeAccessSettings, _RefreshCadenceSettings, _BrokerEndpointSettings):
    """Complete dashboard configuration.

    The grouped bases only organize the fields: the constructor takes every field
    in endpoint, cadence, access, history order, exactly as one flat dataclass.
    """

    history_file: Path | None = None
    history_retention_days: int = 8
    history_sample_interval_seconds: int = 300

    @classmethod
    def from_env(cls) -> DashboardSettings:
        """Load the settings from ``AUTH_USAGE_*`` environment variables.

        Returns:
            Settings whose broker and bind address stay on loopback unless explicitly allowed.

        Raises:
            RuntimeError: If a variable is malformed, out of bounds, unsafe, or a required token is missing.
        """
        broker_url = os.getenv("AUTH_USAGE_BROKER_URL", "http://127.0.0.1:38188").strip().rstrip("/")
        parsed = urlsplit(broker_url)
        allow_remote = environment_flag("AUTH_USAGE_ALLOW_REMOTE_BROKER", default=False)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            message = "AUTH_USAGE_BROKER_URL must be an absolute HTTP(S) URL"
            raise RuntimeError(message)
        if not allow_remote and not is_loopback_host(parsed.hostname):
            message = "AUTH_USAGE_BROKER_URL must be loopback unless AUTH_USAGE_ALLOW_REMOTE_BROKER=1"
            raise RuntimeError(message)

        bind_host = os.getenv("AUTH_USAGE_BIND_HOST", "127.0.0.1").strip()
        allow_public_bind = environment_flag("AUTH_USAGE_ALLOW_PUBLIC_BIND", default=False)
        if not allow_public_bind and not is_loopback_host(bind_host):
            message = "AUTH_USAGE_BIND_HOST must be loopback unless AUTH_USAGE_ALLOW_PUBLIC_BIND=1"
            raise RuntimeError(message)

        safe_probe_enabled = environment_flag("AUTH_USAGE_SAFE_PROBE_ENABLED", default=True)
        configured_token = os.getenv("AUTH_USAGE_BROKER_ADMIN_TOKEN") or os.getenv("AUTH_TOKEN_SERVER_ADMIN_TOKEN")
        admin_token = (configured_token or "").strip()
        if safe_probe_enabled and not admin_token:
            message = "AUTH_USAGE_BROKER_ADMIN_TOKEN or AUTH_TOKEN_SERVER_ADMIN_TOKEN is required"
            raise RuntimeError(message)

        return cls(
            broker_data_dir=Path(os.getenv("AUTH_USAGE_BROKER_DATA_DIR", "/broker-data")).expanduser(),
            broker_url=broker_url,
            broker_admin_token=admin_token,
            bind_host=bind_host,
            bind_port=environment_integer("AUTH_USAGE_BIND_PORT", default=8124, minimum=1024, maximum=65535),
            snapshot_refresh_seconds=environment_integer(
                "AUTH_USAGE_SNAPSHOT_REFRESH_SECONDS",
                default=15,
                minimum=5,
                maximum=300,
            ),
            safe_probe_interval_seconds=environment_integer(
                "AUTH_USAGE_SAFE_PROBE_INTERVAL_SECONDS",
                default=300,
                minimum=60,
                maximum=3600,
            ),
            analytics_probe_interval_seconds=environment_integer(
                "AUTH_USAGE_ANALYTICS_PROBE_INTERVAL_SECONDS",
                default=900,
                minimum=300,
                maximum=86400,
            ),
            manual_probe_min_interval_seconds=environment_integer(
                "AUTH_USAGE_MANUAL_PROBE_MIN_INTERVAL_SECONDS",
                default=60,
                minimum=30,
                maximum=900,
            ),
            stale_after_seconds=environment_integer(
                "AUTH_USAGE_STALE_AFTER_SECONDS",
                default=600,
                minimum=120,
                maximum=86400,
            ),
            analytics_stale_after_seconds=environment_integer(
                "AUTH_USAGE_ANALYTICS_STALE_AFTER_SECONDS",
                default=1800,
                minimum=600,
                maximum=172800,
            ),
            request_timeout_seconds=environment_number(
                "AUTH_USAGE_REQUEST_TIMEOUT_SECONDS",
                default=25.0,
                minimum=2.0,
                maximum=120.0,
            ),
            min_five_hour_remaining_percent=environment_number(
                "AUTH_TOKEN_SERVER_MIN_FIVE_HOUR_REMAINING_PERCENT",
                default=10.0,
                minimum=0.0,
                maximum=100.0,
            ),
            safe_probe_enabled=safe_probe_enabled,
            probe_on_startup=environment_flag("AUTH_USAGE_PROBE_ON_STARTUP", default=True),
            require_proxy_auth=environment_flag("AUTH_USAGE_REQUIRE_PROXY_AUTH", default=True),
            proxy_auth_header=os.getenv("AUTH_USAGE_PROXY_AUTH_HEADER", "x-pitchai-email").strip().lower(),
            history_file=Path(os.getenv("AUTH_USAGE_HISTORY_FILE", "/dashboard-data/usage-samples.json")).expanduser(),
            history_retention_days=environment_integer(
                "AUTH_USAGE_HISTORY_RETENTION_DAYS",
                default=8,
                minimum=7,
                maximum=31,
            ),
            history_sample_interval_seconds=environment_integer(
                "AUTH_USAGE_HISTORY_SAMPLE_INTERVAL_SECONDS",
                default=300,
                minimum=60,
                maximum=1800,
            ),
        )
