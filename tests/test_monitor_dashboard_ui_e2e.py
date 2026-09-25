# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser acceptance coverage for the monitoring dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from domain_checks.testing import verify
from tests.monitor_dashboard_inventory_ui_support import (
    verify_complete_production_inventory,
)
from tests.monitor_dashboard_ui_support import verify_dashboard_identity_and_rendering

if TYPE_CHECKING:
    from tests.monitor_dashboard_server_support import DashboardServer

pytest_plugins = ["tests.monitor_dashboard_server_support"]


@pytest.mark.asyncio
async def test_monitor_dashboard_entra_identity_and_renders(
    dashboard_server: DashboardServer,
) -> None:
    """Verify Entra identity boundaries and responsive dashboard rendering."""
    verify(dashboard_server.base_url.startswith("http://127.0.0.1:"))
    await verify_dashboard_identity_and_rendering(dashboard_server)


@pytest.mark.asyncio
async def test_dashboard_renders_the_complete_production_inventory(
    dashboard_server: DashboardServer,
) -> None:
    """Verify the complete production domain inventory renders correctly."""
    verify(bool(dashboard_server.monitor_token))
    await verify_complete_production_inventory(dashboard_server)
