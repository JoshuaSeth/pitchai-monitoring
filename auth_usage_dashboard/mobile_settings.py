# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validated environment configuration for the protected native-client API."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

type AppAttestEnvironment = Literal["development", "production"]

_MODULE_ROOT = Path(__file__).resolve().parent
_APPLE_PREFIX_PATTERN = re.compile(r"[A-Z0-9]{10}")
_BUNDLE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+")
_INTEGER_PATTERN = re.compile(r"[+-]?[0-9]{1,10}")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


class MobileSettingsError(ValueError):
    """A native-client environment value violates the fail-closed contract."""


@dataclass(frozen=True)
class MobileApplication:
    """Apple application identity bound into App Attest requests."""

    app_id_prefix: str = ""
    bundle_id: str = ""

    @property
    def app_id(self) -> str:
        """Return the complete Apple application identifier."""
        return f"{self.app_id_prefix}.{self.bundle_id}"


@dataclass(frozen=True)
class AppAttestSettings:
    """Pinned certificate, registry, and enrollment configuration."""

    environment: AppAttestEnvironment = "development"
    registry_file: Path = Path("/dashboard-data/mobile-app-attest.json")
    root_certificate: Path = _MODULE_ROOT / "certs" / "apple-app-attestation-root-ca.crt"
    enrollment_enabled: bool = False
    max_keys: int = 2


@dataclass(frozen=True)
class ChallengeSettings:
    """Bounds for native-client challenge issuance."""

    ttl_seconds: int = 120
    max_pending: int = 128


@dataclass(frozen=True)
class MobileSettings:
    """Configuration for App Attest enrollment, requests, and refresh cadence."""

    enabled: bool = False
    application: MobileApplication = field(default_factory=MobileApplication)
    app_attest: AppAttestSettings = field(default_factory=AppAttestSettings)
    challenges: ChallengeSettings = field(default_factory=ChallengeSettings)
    background_refresh_seconds: int = 900

    @classmethod
    def from_env(cls) -> MobileSettings:
        """Load native-client settings without enabling enrollment by default.

        Returns:
            Fully validated mobile settings.

        """
        enabled = _environment_flag("AUTH_USAGE_MOBILE_ENABLED", default=False)
        application = MobileApplication(
            app_id_prefix=_environment_text("AUTH_USAGE_MOBILE_APP_ID_PREFIX"),
            bundle_id=_environment_text("AUTH_USAGE_MOBILE_BUNDLE_ID"),
        )
        if enabled:
            _validate_application_identity(application)
        return cls(
            enabled=enabled,
            application=application,
            app_attest=_app_attest_settings_from_env(),
            challenges=ChallengeSettings(
                ttl_seconds=_bounded_integer(
                    "AUTH_USAGE_MOBILE_CHALLENGE_TTL_SECONDS",
                    default=120,
                    minimum=30,
                    maximum=300,
                ),
                max_pending=_bounded_integer(
                    "AUTH_USAGE_MOBILE_CHALLENGE_MAX_PENDING",
                    default=128,
                    minimum=8,
                    maximum=1_024,
                ),
            ),
            background_refresh_seconds=_bounded_integer(
                "AUTH_USAGE_MOBILE_BACKGROUND_REFRESH_SECONDS",
                default=900,
                minimum=900,
                maximum=86_400,
            ),
        )


def _app_attest_settings_from_env() -> AppAttestSettings:
    return AppAttestSettings(
        environment=_environment_choice(),
        registry_file=_environment_path(
            "AUTH_USAGE_MOBILE_APP_ATTEST_REGISTRY_FILE",
            default=Path("/dashboard-data/mobile-app-attest.json"),
        ),
        root_certificate=_environment_path(
            "AUTH_USAGE_MOBILE_APP_ATTEST_ROOT_CERTIFICATE",
            default=_MODULE_ROOT / "certs" / "apple-app-attestation-root-ca.crt",
        ),
        enrollment_enabled=_environment_flag(
            "AUTH_USAGE_MOBILE_APP_ATTEST_ENROLLMENT_ENABLED",
            default=False,
        ),
        max_keys=_bounded_integer(
            "AUTH_USAGE_MOBILE_APP_ATTEST_MAX_KEYS",
            default=2,
            minimum=1,
            maximum=8,
        ),
    )


def _environment_choice() -> AppAttestEnvironment:
    value = _environment_text(
        "AUTH_USAGE_MOBILE_APP_ATTEST_ENVIRONMENT",
        default="development",
    ).casefold()
    if value == "development":
        return "development"
    if value == "production":
        return "production"
    message = "AUTH_USAGE_MOBILE_APP_ATTEST_ENVIRONMENT must be development or production"
    raise MobileSettingsError(message)


def _environment_text(name: str, *, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _environment_path(name: str, *, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).expanduser()


def _environment_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    message = f"{name} must be a boolean"
    raise MobileSettingsError(message)


def _bounded_integer(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    normalized = "" if raw is None else raw.strip()
    if raw is not None and _INTEGER_PATTERN.fullmatch(normalized) is None:
        message = f"{name} must be an integer"
        raise MobileSettingsError(message)
    value = default if raw is None else int(normalized)
    if not minimum <= value <= maximum:
        message = f"{name} must be between {minimum} and {maximum}"
        raise MobileSettingsError(message)
    return value


def _validate_application_identity(application: MobileApplication) -> None:
    if _APPLE_PREFIX_PATTERN.fullmatch(application.app_id_prefix) is None:
        message = "AUTH_USAGE_MOBILE_APP_ID_PREFIX must be a 10-character Apple App ID prefix"
        raise MobileSettingsError(message)
    if _BUNDLE_IDENTIFIER_PATTERN.fullmatch(application.bundle_id) is None:
        message = "AUTH_USAGE_MOBILE_BUNDLE_ID must be an explicit bundle identifier"
        raise MobileSettingsError(message)
