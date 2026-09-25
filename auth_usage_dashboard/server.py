# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the authentication usage dashboard ASGI server."""

from __future__ import annotations

import uvicorn

from .app import create_app
from .settings import DashboardSettings


def main() -> None:
    """Run main."""
    settings = DashboardSettings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.bind_host,
        port=settings.bind_port,
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
