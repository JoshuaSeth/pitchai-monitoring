# Copyright (c) 2026 PitchAI. All rights reserved.
"""Install monitoring v2 enrichment into the existing FastAPI registry app."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .evidence import router as evidence_router
from .registry_runtime import legacy_dashboard
from .summary import build_dashboard_summary

if TYPE_CHECKING:
    from .registry_runtime import DashboardBuilder
    from .web_runtime import Application


def install_monitoring_v2(app: Application) -> None:
    """Replace summary composition and register the protected evidence route."""
    legacy_dashboard.build_dashboard_summary = cast(
        "DashboardBuilder",
        cast("object", build_dashboard_summary),
    )
    app.include_router(evidence_router)
