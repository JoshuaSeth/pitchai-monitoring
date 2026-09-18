# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the protected capacity dashboard and durable usage-history collector."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import uvicorn

from . import mobile_app as dashboard_app
from .settings import DashboardSettings
from .timeseries_collector import UsageHistoryCollector

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    type AsgiApplication = Callable[..., Awaitable[None]]


def main() -> None:
    """Serve the dashboard while owning exactly one periodic history writer."""
    settings = DashboardSettings.from_env()
    factory = cast(
        "Callable[[DashboardSettings], AsgiApplication]",
        vars(dashboard_app)["create_app"],
    )
    application = factory(settings)
    collector = UsageHistoryCollector.from_settings(settings)
    collector.start()
    try:
        uvicorn.run(
            application,
            host=settings.bind_host,
            port=settings.bind_port,
            access_log=False,
            server_header=False,
        )
    finally:
        collector.stop()


if __name__ == "__main__":
    main()
