from __future__ import annotations

import os

import uvicorn

from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings


def main() -> None:
    host = os.getenv("E2E_REGISTRY_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.getenv("E2E_REGISTRY_PORT", "8111"))
    settings = RegistrySettings()
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

