# Copyright (c) 2026 PitchAI. All rights reserved.
"""Install monitoring v2 enrichment into the existing FastAPI registry app."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .evidence import router as evidence_router
from .monitor_data_cache import CachedMonitorDataLoader
from .registry_runtime import legacy_dashboard
from .summary import build_dashboard_summary

if TYPE_CHECKING:
    from .registry_runtime import DashboardBuilder
    from .web_runtime import Application

_monitor_data_loader = CachedMonitorDataLoader(
    delegate=legacy_dashboard.load_monitor_data,
)


def install_monitoring_v2(app: Application) -> None:
    """Install summary composition, parsed-data caching, and evidence routing."""
    legacy_dashboard.build_dashboard_summary = cast(
        "DashboardBuilder",
        cast("object", build_dashboard_summary),
    )
    legacy_dashboard.load_monitor_data = _monitor_data_loader
    app.include_router(evidence_router)
