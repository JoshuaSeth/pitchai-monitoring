# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compose the unchanged operator dashboard with protected native routes."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from .mobile_challenges import ChallengeStore
from .mobile_registry import AppAttestRegistry, RegistryConfiguration
from .mobile_route_state import MobileRouteConfiguration, MobileRouteDependencies
from .mobile_routes import router
from .mobile_settings import MobileSettings
from .service import CapacityService
from .settings import DashboardSettings
from .source import BrokerStateSource

if TYPE_CHECKING:
    from .mobile_route_state import CapacityServiceSurface, MobileStateContainer
    from .mobile_web_runtime import WebApplication
    from .service import StateSource


class _BaseApplicationFactory(Protocol):
    def __call__(
        self,
        settings: DashboardSettings,
        *,
        source: StateSource,
        service: CapacityService,
    ) -> WebApplication:
        """Create the established operator dashboard application."""
        raise NotImplementedError

    def application_factory_marker(self) -> None:
        """Identify the dynamic factory contract to static tooling."""
        raise NotImplementedError


_APP_MODULE = cast(
    "dict[str, object]",
    vars(import_module("auth_usage_dashboard.app")),
)
_BASE_APPLICATION_FACTORY = cast("_BaseApplicationFactory", _APP_MODULE["create_app"])


def create_app(
    settings: DashboardSettings | None = None,
    *,
    source: StateSource | None = None,
    service: CapacityService | None = None,
    mobile_settings: MobileSettings | None = None,
) -> WebApplication:
    """Create the dashboard and install native routes only when enabled.

    Returns:
        The composed ASGI application.
    """
    resolved_settings = settings or DashboardSettings.from_env()
    resolved_source = source or _source_from_settings(resolved_settings)
    resolved_service = service or CapacityService(resolved_settings, resolved_source)
    application = _BASE_APPLICATION_FACTORY(
        resolved_settings,
        source=resolved_source,
        service=resolved_service,
    )
    native_settings = mobile_settings or MobileSettings.from_env()
    if native_settings.enabled:
        _install_native_routes(
            application,
            dashboard_settings=resolved_settings,
            mobile_settings=native_settings,
            service=resolved_service,
        )
    return application


def _source_from_settings(settings: DashboardSettings) -> StateSource:
    return BrokerStateSource(
        data_dir=settings.broker_data_dir,
        broker_url=settings.broker_url,
        admin_token=settings.broker_admin_token,
        request_timeout_seconds=settings.request_timeout_seconds,
    )


def _install_native_routes(
    application: WebApplication,
    *,
    dashboard_settings: DashboardSettings,
    mobile_settings: MobileSettings,
    service: CapacityService,
) -> None:
    attest = mobile_settings.app_attest
    registry = AppAttestRegistry(
        RegistryConfiguration(
            path=attest.registry_file,
            root_certificate_path=attest.root_certificate,
            app_id=mobile_settings.application.app_id,
            environment=attest.environment,
            max_keys=attest.max_keys,
            enrollment_enabled=attest.enrollment_enabled,
        ),
    )
    challenges = ChallengeStore(
        ttl_seconds=mobile_settings.challenges.ttl_seconds,
        max_pending=mobile_settings.challenges.max_pending,
    )
    service_surface = cast("CapacityServiceSurface", cast("object", service))
    dependencies = MobileRouteDependencies(
        registry=registry,
        challenges=challenges,
        service=service_surface,
        configuration=MobileRouteConfiguration(
            challenge_ttl_seconds=mobile_settings.challenges.ttl_seconds,
            manual_refresh_min_interval_seconds=dashboard_settings.manual_probe_min_interval_seconds,
            background_refresh_seconds=mobile_settings.background_refresh_seconds,
        ),
    )
    state = cast("MobileStateContainer", cast("object", application.state))
    state.mobile_route_dependencies = dependencies
    application.include_router(router)
