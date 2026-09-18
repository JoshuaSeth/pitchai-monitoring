# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed adapters for established E2E registry application contracts."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from .json_types import JsonObject
    from .web_runtime import Application

type SettingValue = str | bool | int | tuple[str, ...]


class RegistrySettings(NamedTuple):
    """Registry settings fields consumed by monitoring v2."""

    monitor_token: str
    monitor_state_path: str
    monitor_config_path: str
    dashboard_identity_header: str
    dashboard_max_points: int


@dataclass(frozen=True)
class MonitorData:
    """Duck-typed retained monitor data accepted by the legacy summary builder."""

    state: JsonObject
    config: JsonObject
    state_path: str
    config_path: str
    loaded_at_ts: float
    state_error: str | None


class DashboardBuilder(Protocol):
    """Legacy and v2 dashboard summary function contract."""

    def __call__(
        self,
        *,
        data: MonitorData,
        now_ts: float,
        e2e_status_summary: JsonObject | None,
        e2e_dispatch_runs: list[JsonObject] | None,
    ) -> JsonObject:
        """Build one monitoring dashboard summary."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the adapter contract name."""
        raise NotImplementedError


class LegacyDashboard(Protocol):
    """Mutable summary hook retained by the established registry app."""

    build_dashboard_summary: DashboardBuilder

    def contract_name(self) -> str:
        """Return the adapter contract name."""
        raise NotImplementedError

    def supports_builder_replacement(self) -> bool:
        """Report support for runtime summary-builder replacement."""
        raise NotImplementedError


class _RegistrySettingsFactory(Protocol):
    def __call__(self, **values: SettingValue) -> RegistrySettings:
        """Construct one established registry settings object."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the adapter contract name."""
        raise NotImplementedError


class _SettingsModule(NamedTuple):
    RegistrySettings: _RegistrySettingsFactory


class _AppModule(NamedTuple):
    create_app: Callable[[RegistrySettings | None], Application]


_SETTINGS = cast("_SettingsModule", cast("object", import_module("e2e_registry.settings")))
_APP = cast("_AppModule", cast("object", import_module("e2e_registry.app")))
legacy_dashboard = cast(
    "LegacyDashboard",
    cast("object", import_module("e2e_registry.monitor_dashboard")),
)


@dataclass(frozen=True)
class RegistryPaths:
    """Isolated registry persistence paths."""

    db_path: str
    artifacts_dir: str
    tests_dir: str


@dataclass(frozen=True)
class RegistryTokens:
    """Ephemeral isolated registry credentials."""

    admin_token: str
    monitor_token: str
    runner_token: str


@dataclass(frozen=True)
class PolicySettingsInput:
    """Inputs for one isolated strict base-URL policy fixture."""

    paths: RegistryPaths
    tokens: RegistryTokens
    explicit_hosts: tuple[str, ...]
    allow_monitored_domains: bool
    monitor_config_path: str


@dataclass(frozen=True)
class DashboardSettingsInput:
    """Inputs for one isolated production-shaped dashboard fixture."""

    paths: RegistryPaths
    tokens: RegistryTokens
    state_path: str
    config_path: str


def production_registry_app() -> Application:
    """Construct the production registry app from environment settings.

    Returns:
        The configured production FastAPI registry application.
    """
    settings = _SETTINGS.RegistrySettings()
    return _APP.create_app(settings)


def policy_registry_settings(
    inputs: PolicySettingsInput,
) -> RegistrySettings:
    """Construct the isolated strict base-URL policy fixture settings.

    Returns:
        The established settings for the isolated policy fixture.
    """
    return _SETTINGS.RegistrySettings(
        db_path=inputs.paths.db_path,
        artifacts_dir=inputs.paths.artifacts_dir,
        tests_dir=inputs.paths.tests_dir,
        admin_token=inputs.tokens.admin_token,
        monitor_token=inputs.tokens.monitor_token,
        runner_token=inputs.tokens.runner_token,
        alerts_enabled=False,
        dispatch_enabled=False,
        strict_base_url_policy=True,
        base_url_allowed_hosts=inputs.explicit_hosts,
        base_url_allow_monitored_domains=inputs.allow_monitored_domains,
        monitor_config_path=inputs.monitor_config_path,
        public_base_url="https://monitoring.pitchai.net",
    )


def dashboard_registry_settings(
    inputs: DashboardSettingsInput,
) -> RegistrySettings:
    """Construct the isolated production-shaped dashboard fixture settings.

    Returns:
        The established settings for the isolated dashboard fixture.
    """
    return _SETTINGS.RegistrySettings(
        db_path=inputs.paths.db_path,
        artifacts_dir=inputs.paths.artifacts_dir,
        tests_dir=inputs.paths.tests_dir,
        admin_token=inputs.tokens.admin_token,
        monitor_token=inputs.tokens.monitor_token,
        runner_token=inputs.tokens.runner_token,
        alerts_enabled=False,
        dispatch_enabled=False,
        public_base_url="",
        monitor_state_path=inputs.state_path,
        monitor_config_path=inputs.config_path,
        dashboard_max_points=500,
    )


def create_registry_app(settings: RegistrySettings) -> Application:
    """Create the established registry app through the typed boundary.

    Returns:
        The configured FastAPI registry application.

    Raises:
        ValueError: If dashboard history retention is disabled.
    """
    if settings.dashboard_max_points < 1:
        message = "registry dashboard_max_points must be positive"
        raise ValueError(message)
    return _APP.create_app(settings)
