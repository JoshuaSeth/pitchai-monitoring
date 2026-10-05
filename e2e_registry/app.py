# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry application assembly with ordered routes and late-bound shared state."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from e2e_registry.app_access import RegistryAccess
from e2e_registry.app_admin_routes import router as admin_router
from e2e_registry.app_context import RegistryContext
from e2e_registry.app_entry_routes import RegistryEntryRoutes
from e2e_registry.app_host_policy import host_is_reserved_or_non_public as _host_is_reserved_or_non_public
from e2e_registry.app_host_policy import load_monitored_allowlist_hosts as _load_monitored_allowlist_hosts
from e2e_registry.app_host_policy import url_host as _url_host
from e2e_registry.app_inputs import normalize_pitchai_email as _normalize_pitchai_email
from e2e_registry.app_inputs import normalize_test_kind as _normalize_test_kind
from e2e_registry.app_inputs import safe_filename as _safe_filename
from e2e_registry.app_monitoring_routes import install_monitoring_routes
from e2e_registry.app_read_routes import router as read_router
from e2e_registry.app_runner_routes import router as runner_router
from e2e_registry.app_source_routes import router as source_router
from e2e_registry.app_startup import RegistryStartup
from e2e_registry.app_test_creation import router as test_creation_router
from e2e_registry.app_test_routes import lookup_router as test_lookup_router
from e2e_registry.app_test_routes import router as test_mutation_router
from e2e_registry.app_ui_mutation_routes import router as ui_mutation_router
from e2e_registry.app_ui_read_routes import router as ui_read_router
from e2e_registry.app_ui_read_routes import run_router as ui_run_router
from e2e_registry.app_ui_session_routes import router as ui_session_router
from e2e_registry.app_ui_source_routes import router as ui_source_router
from e2e_registry.app_ui_upload_routes import router as ui_upload_router
from e2e_registry.app_upload_routes import router as upload_router
from e2e_registry.settings import RegistrySettings

__all__ = [
    "_host_is_reserved_or_non_public", "_load_monitored_allowlist_hosts", "_normalize_pitchai_email",
    "_normalize_test_kind", "_safe_filename", "_url_host", "app", "create_app",
]


def create_app(settings: RegistrySettings | None = None) -> FastAPI:
    """Assemble the existing state, startup handler and route order.

    Returns:
        The registry ASGI application, without starting lifespan or opening a database.
    """
    application = FastAPI(title="PitchAI E2E Registry", version="0.1.0")
    application.state.settings = settings or RegistrySettings()
    application.state.monitor_cache = {"loaded_at_ts": 0.0, "state_mtime": None, "config_mtime": None, "data": None}
    templates_dir = Path(__file__).parent / "templates"
    application.state.templates = Jinja2Templates(directory=str(templates_dir))
    dashboard_assets_dir = Path(__file__).parent / "static"
    application.mount("/dashboard/assets", StaticFiles(directory=str(dashboard_assets_dir)), name="dashboard-assets")
    context = RegistryContext(application)
    access = RegistryAccess(context)
    application.router.add_event_handler("startup", RegistryStartup(context).run)

    application.add_api_route("/health", RegistryEntryRoutes.health, response_model=dict)
    application.add_api_route("/", RegistryEntryRoutes.root)
    application.include_router(ui_session_router)
    application.include_router(ui_read_router)
    application.include_router(ui_mutation_router)
    application.include_router(ui_source_router)
    application.include_router(ui_run_router)
    application.include_router(ui_upload_router)
    install_monitoring_routes(context, access)
    application.include_router(admin_router)
    application.include_router(test_creation_router)
    application.include_router(upload_router)
    application.include_router(test_lookup_router)
    application.include_router(source_router)
    application.include_router(test_mutation_router)
    application.include_router(read_router)
    application.include_router(runner_router)
    return application


app = create_app()
