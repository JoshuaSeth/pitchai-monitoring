# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the dashboard with the aggregate scheduling-capacity contract."""

from __future__ import annotations

from contextlib import ExitStack

from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import uvicorn_runner
from .settings import DashboardSettings
from .timeseries_collector import UsageHistoryCollector


def main() -> None:
    """Serve the protected dashboard while owning one history writer."""
    settings = DashboardSettings.from_env()
    application = create_scheduling_app(settings)
    collector = UsageHistoryCollector.from_settings(settings)
    collector.start()
    with ExitStack() as cleanup:
        cleanup.callback(collector.stop)
        uvicorn_runner(
            application,
            host=settings.bind_host,
            port=settings.bind_port,
            access_log=False,
            server_header=False,
        )


if __name__ == "__main__":
    main()
