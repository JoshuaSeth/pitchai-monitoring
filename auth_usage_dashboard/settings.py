from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
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


@dataclass(frozen=True)
class DashboardSettings:
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
    mobile_enabled: bool = False
    mobile_app_id_prefix: str = ""
    mobile_bundle_id: str = ""
    mobile_app_attest_environment: str = "development"
    mobile_app_attest_registry_file: Path = Path(
        "/dashboard-data/mobile-app-attest.json"
    )
    mobile_app_attest_root_certificate: Path = (
        ROOT / "certs" / "apple-app-attestation-root-ca.crt"
    )
    mobile_app_attest_enrollment_enabled: bool = False
    mobile_app_attest_max_keys: int = 2
    mobile_challenge_ttl_seconds: int = 120
    mobile_challenge_max_pending: int = 128
    mobile_background_refresh_seconds: int = 900

    @classmethod
    def from_env(cls) -> "DashboardSettings":
        broker_url = os.getenv("AUTH_USAGE_BROKER_URL", "http://127.0.0.1:38188").strip().rstrip("/")
        parsed = urlsplit(broker_url)
        allow_remote = _env_bool("AUTH_USAGE_ALLOW_REMOTE_BROKER", False)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError("AUTH_USAGE_BROKER_URL must be an absolute HTTP(S) URL")
        if not allow_remote and not _is_loopback_host(parsed.hostname):
            raise RuntimeError("AUTH_USAGE_BROKER_URL must be loopback unless AUTH_USAGE_ALLOW_REMOTE_BROKER=1")

        bind_host = os.getenv("AUTH_USAGE_BIND_HOST", "127.0.0.1").strip()
        if not _env_bool("AUTH_USAGE_ALLOW_PUBLIC_BIND", False) and not _is_loopback_host(bind_host):
            raise RuntimeError("AUTH_USAGE_BIND_HOST must be loopback unless AUTH_USAGE_ALLOW_PUBLIC_BIND=1")

        safe_probe_enabled = _env_bool("AUTH_USAGE_SAFE_PROBE_ENABLED", True)
        admin_token = (
            os.getenv("AUTH_USAGE_BROKER_ADMIN_TOKEN")
            or os.getenv("AUTH_TOKEN_SERVER_ADMIN_TOKEN")
            or ""
        ).strip()
        if safe_probe_enabled and not admin_token:
            raise RuntimeError("AUTH_USAGE_BROKER_ADMIN_TOKEN or AUTH_TOKEN_SERVER_ADMIN_TOKEN is required")

        mobile_enabled = _env_bool("AUTH_USAGE_MOBILE_ENABLED", False)
        mobile_app_id_prefix = os.getenv(
            "AUTH_USAGE_MOBILE_APP_ID_PREFIX", ""
        ).strip()
        mobile_bundle_id = os.getenv("AUTH_USAGE_MOBILE_BUNDLE_ID", "").strip()
        mobile_environment = os.getenv(
            "AUTH_USAGE_MOBILE_APP_ATTEST_ENVIRONMENT", "development"
        ).strip().lower()
        if mobile_environment not in {"development", "production"}:
            raise RuntimeError(
                "AUTH_USAGE_MOBILE_APP_ATTEST_ENVIRONMENT must be development or production"
            )
        if mobile_enabled:
            if re.fullmatch(r"[A-Z0-9]{10}", mobile_app_id_prefix) is None:
                raise RuntimeError(
                    "AUTH_USAGE_MOBILE_APP_ID_PREFIX must be a 10-character Apple App ID prefix"
                )
            if (
                re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+", mobile_bundle_id)
                is None
            ):
                raise RuntimeError(
                    "AUTH_USAGE_MOBILE_BUNDLE_ID must be an explicit bundle identifier"
                )

        return cls(
            broker_data_dir=Path(os.getenv("AUTH_USAGE_BROKER_DATA_DIR", "/broker-data")).expanduser(),
            broker_url=broker_url,
            broker_admin_token=admin_token,
            bind_host=bind_host,
            bind_port=_env_int("AUTH_USAGE_BIND_PORT", 8124, minimum=1024, maximum=65535),
            snapshot_refresh_seconds=_env_int(
                "AUTH_USAGE_SNAPSHOT_REFRESH_SECONDS", 15, minimum=5, maximum=300
            ),
            safe_probe_interval_seconds=_env_int(
                "AUTH_USAGE_SAFE_PROBE_INTERVAL_SECONDS", 300, minimum=60, maximum=3600
            ),
            analytics_probe_interval_seconds=_env_int(
                "AUTH_USAGE_ANALYTICS_PROBE_INTERVAL_SECONDS", 900, minimum=300, maximum=86400
            ),
            manual_probe_min_interval_seconds=_env_int(
                "AUTH_USAGE_MANUAL_PROBE_MIN_INTERVAL_SECONDS", 60, minimum=30, maximum=900
            ),
            stale_after_seconds=_env_int(
                "AUTH_USAGE_STALE_AFTER_SECONDS", 600, minimum=120, maximum=86400
            ),
            analytics_stale_after_seconds=_env_int(
                "AUTH_USAGE_ANALYTICS_STALE_AFTER_SECONDS", 1800, minimum=600, maximum=172800
            ),
            request_timeout_seconds=_env_float(
                "AUTH_USAGE_REQUEST_TIMEOUT_SECONDS", 25.0, minimum=2.0, maximum=120.0
            ),
            min_five_hour_remaining_percent=_env_float(
                "AUTH_TOKEN_SERVER_MIN_FIVE_HOUR_REMAINING_PERCENT", 10.0, minimum=0.0, maximum=100.0
            ),
            safe_probe_enabled=safe_probe_enabled,
            probe_on_startup=_env_bool("AUTH_USAGE_PROBE_ON_STARTUP", True),
            require_proxy_auth=_env_bool("AUTH_USAGE_REQUIRE_PROXY_AUTH", True),
            proxy_auth_header=os.getenv("AUTH_USAGE_PROXY_AUTH_HEADER", "x-pitchai-email").strip().lower(),
            history_file=Path(
                os.getenv("AUTH_USAGE_HISTORY_FILE", "/dashboard-data/usage-samples.json")
            ).expanduser(),
            history_retention_days=_env_int(
                "AUTH_USAGE_HISTORY_RETENTION_DAYS", 8, minimum=7, maximum=31
            ),
            history_sample_interval_seconds=_env_int(
                "AUTH_USAGE_HISTORY_SAMPLE_INTERVAL_SECONDS", 300, minimum=60, maximum=1800
            ),
            mobile_enabled=mobile_enabled,
            mobile_app_id_prefix=mobile_app_id_prefix,
            mobile_bundle_id=mobile_bundle_id,
            mobile_app_attest_environment=mobile_environment,
            mobile_app_attest_registry_file=Path(
                os.getenv(
                    "AUTH_USAGE_MOBILE_APP_ATTEST_REGISTRY_FILE",
                    "/dashboard-data/mobile-app-attest.json",
                )
            ).expanduser(),
            mobile_app_attest_root_certificate=Path(
                os.getenv(
                    "AUTH_USAGE_MOBILE_APP_ATTEST_ROOT_CERTIFICATE",
                    str(ROOT / "certs" / "apple-app-attestation-root-ca.crt"),
                )
            ).expanduser(),
            mobile_app_attest_enrollment_enabled=_env_bool(
                "AUTH_USAGE_MOBILE_APP_ATTEST_ENROLLMENT_ENABLED", False
            ),
            mobile_app_attest_max_keys=_env_int(
                "AUTH_USAGE_MOBILE_APP_ATTEST_MAX_KEYS", 2, minimum=1, maximum=8
            ),
            mobile_challenge_ttl_seconds=_env_int(
                "AUTH_USAGE_MOBILE_CHALLENGE_TTL_SECONDS",
                120,
                minimum=30,
                maximum=300,
            ),
            mobile_challenge_max_pending=_env_int(
                "AUTH_USAGE_MOBILE_CHALLENGE_MAX_PENDING",
                128,
                minimum=8,
                maximum=1024,
            ),
            mobile_background_refresh_seconds=_env_int(
                "AUTH_USAGE_MOBILE_BACKGROUND_REFRESH_SECONDS",
                900,
                minimum=900,
                maximum=86400,
            ),
        )
