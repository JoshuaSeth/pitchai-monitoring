# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build the authenticated FastAPI capacity dashboard application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .app_routes import DashboardRoutes
from .service import CapacityService
from .settings import DashboardSettings
from .source import BrokerStateSource

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from .app_routes import TemplateLoader
    from .service import StateSource

ROOT = Path(__file__).resolve().parent


def create_app(
    settings: DashboardSettings | None = None,
    *,
    source: StateSource | None = None,
    service: CapacityService | None = None,
) -> FastAPI:
    """Create create app.

    Returns:
        The resulting value.

    """
    settings = settings or DashboardSettings.from_env()
    if service is None:
        if source is None:
            source = BrokerStateSource(
                data_dir=settings.broker_data_dir,
                broker_url=settings.broker_url,
                admin_token=settings.broker_admin_token,
                request_timeout_seconds=settings.request_timeout_seconds,
            )
        service = CapacityService(settings, source)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Handle lifespan."""
        app.state.capacity_service = service
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(
        title="PitchAI Codex Capacity",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    template_loader = cast("TemplateLoader", templates.get_template)
    app.state.templates = templates
    routes = DashboardRoutes(
        settings=settings,
        service=service,
        template_loader=template_loader,
    )
    routes.register(app)

    return app
