# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the production E2E registry and monitoring dashboard service."""

from __future__ import annotations

import os

import uvicorn

from .monitoring_v2 import install_monitoring_v2
from .monitoring_v2.legacy import production_registry_app


def main() -> None:
    """Create the registry app, install monitoring v2, and serve HTTP."""
    host = os.getenv("E2E_REGISTRY_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("E2E_REGISTRY_PORT", "8111"))
    app = production_registry_app()
    install_monitoring_v2(app)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
