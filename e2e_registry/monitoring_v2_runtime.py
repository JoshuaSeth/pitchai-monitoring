# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary from the legacy registry to monitoring v2."""

from __future__ import annotations

from importlib import import_module
from typing import NamedTuple, Protocol, cast


class RegistryApplication(NamedTuple):
    """Opaque typed handle for the established registry application."""

    runtime_marker: str


class MonitoringInstaller(Protocol):
    """Monitoring dashboard installer contract."""

    def __call__(self, application: RegistryApplication) -> None:
        """Install monitoring v2 into one registry application."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class RegistryApplicationFactory(Protocol):
    """Production registry application factory contract."""

    def __call__(self) -> RegistryApplication:
        """Return the production registry application."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _DashboardModule(NamedTuple):
    install_monitoring_v2: object


class _LegacyModule(NamedTuple):
    production_registry_app: object


_DASHBOARD = cast(
    "_DashboardModule",
    cast("object", import_module("monitoring_v2.install")),
)
_LEGACY = cast(
    "_LegacyModule",
    cast("object", import_module("monitoring_v2.registry_runtime")),
)
install_monitoring_v2 = cast("MonitoringInstaller", _DASHBOARD.install_monitoring_v2)
production_registry_app = cast(
    "RegistryApplicationFactory",
    _LEGACY.production_registry_app,
)
