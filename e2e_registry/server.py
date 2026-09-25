# Copyright (c) 2026 PitchAI. All rights reserved.
"""Uvicorn entry point for the E2E registry web service."""

from __future__ import annotations

import ipaddress
import os

import uvicorn

from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings


def main() -> None:
    """Build settings and run the registry HTTP service."""
    default_host = str(ipaddress.ip_address(0))
    host = os.getenv("E2E_REGISTRY_HOST", default_host).strip() or default_host
    port = int(os.getenv("E2E_REGISTRY_PORT", "8111"))
    settings = RegistrySettings()
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
