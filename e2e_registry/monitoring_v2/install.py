# Copyright (c) 2026 PitchAI. All rights reserved.
"""Install monitoring v2 enrichment into the existing FastAPI registry app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry import monitor_dashboard as legacy_dashboard
from e2e_registry.monitoring_v2.evidence import router as evidence_router
from e2e_registry.monitoring_v2.summary import build_dashboard_summary

if TYPE_CHECKING:
    from fastapi import FastAPI


def install_monitoring_v2(app: FastAPI) -> None:
    """Replace summary composition and register the protected evidence route."""
    legacy_dashboard.build_dashboard_summary = build_dashboard_summary
    app.include_router(evidence_router)
