# Copyright (c) 2026 PitchAI. All rights reserved.
"""FastAPI composition root for the PitchAI E2E registry."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from e2e_registry import db as dbm
from e2e_registry.app_context import RegistryAppContext
from e2e_registry.app_policy import (
    BaseUrlPolicy,
)
from e2e_registry.app_policy import (
    load_monitored_allowlist_hosts as _load_monitored_allowlist_hosts,
)
from e2e_registry.app_routes_core import router as core_router
from e2e_registry.app_routes_monitor import router as monitor_router
from e2e_registry.app_routes_runner import router as runner_router
from e2e_registry.app_routes_test_actions import router as test_actions_router
from e2e_registry.app_routes_test_create import router as test_create_router
from e2e_registry.app_routes_test_read import router as test_read_router
from e2e_registry.app_routes_test_source import router as test_source_router
from e2e_registry.app_routes_ui_tests import router as ui_tests_router
from e2e_registry.app_routes_ui_upload import router as ui_upload_router
from e2e_registry.settings import RegistrySettings
from e2e_registry.storage_permissions import migrate_registry_storage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

LOGGER = logging.getLogger("e2e-registry")


def _initialize_registry(settings: RegistrySettings, context: RegistryAppContext) -> None:
    dbm.ensure_schema(settings)
    Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.tests_dir).mkdir(parents=True, exist_ok=True)
    migrate_registry_storage(
        database_path=Path(settings.db_path),
        tests_directory=Path(settings.tests_dir),
        artifacts_directory=Path(settings.artifacts_dir),
    )
    quarantined = context.base_url_policy.quarantine_disallowed_tests()
    if quarantined > 0:
        LOGGER.warning("Quarantined disallowed e2e tests count=%s", quarantined)


def create_app(settings: RegistrySettings | None = None) -> FastAPI:
    """Compose the registry application from focused route modules.

    Returns:
        The configured FastAPI application.
    """
    configured_settings = settings or RegistrySettings()
    templates_directory = Path(__file__).parent / "templates"
    context = RegistryAppContext(
        settings=configured_settings,
        templates=Jinja2Templates(directory=str(templates_directory)),
        base_url_policy=BaseUrlPolicy(configured_settings),
    )

    @asynccontextmanager
    async def _lifespan(_application: FastAPI) -> AsyncGenerator[None]:
        await asyncio.to_thread(_initialize_registry, configured_settings, context)
        yield

    application = FastAPI(title="PitchAI E2E Registry", version="0.1.0", lifespan=_lifespan)
    application.state.settings = configured_settings
    application.state.registry_context = context
    assets_directory = Path(__file__).parent / "static"
    application.mount(
        "/dashboard/assets",
        StaticFiles(directory=str(assets_directory)),
        name="dashboard-assets",
    )

    application.include_router(core_router)
    application.include_router(ui_tests_router)
    application.include_router(ui_upload_router)
    application.include_router(monitor_router)
    application.include_router(test_create_router)
    application.include_router(test_source_router)
    application.include_router(test_read_router)
    application.include_router(test_actions_router)
    application.include_router(runner_router)
    return application


app = create_app()

__all__ = ["_load_monitored_allowlist_hosts", "app", "create_app"]
