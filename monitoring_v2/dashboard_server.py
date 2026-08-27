# Copyright (c) 2026 PitchAI. All rights reserved.
"""Low-footprint local server fixture for monitoring dashboard browser tests."""

from __future__ import annotations

import json
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import uvicorn

from e2e_registry.hotpath_install import install_hotpath_monitoring

from .install import install_monitoring_v2
from .network_gateway import free_tcp_port
from .registry_runtime import (
    DashboardSettingsInput,
    RegistryPaths,
    RegistryTokens,
    create_registry_app,
    dashboard_registry_settings,
    legacy_dashboard,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from e2e_registry.hotpath_install import HotpathApplication

    from .json_types import JsonObject
    from .registry_runtime import RegistrySettings

_START_ATTEMPTS = 80
_START_RETRY_SECONDS = 0.05
_SHUTDOWN_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class DashboardServer:
    """Address and monitor token for one isolated dashboard test server."""

    base_url: str
    monitor_token: str


def _write_monitor_fixture(root: Path) -> tuple[Path, Path]:
    now = time.time()
    state: JsonObject = {
        "version": 5,
        "updated_at": now,
        "last_ok": {"a.example": True},
        "fail_streak": {"a.example": 0},
        "success_streak": {"a.example": 3},
        "history": {"a.example": [[now - 60, True, 110.0, 400.0, 200]]},
        "events": [],
    }
    state_path = root / "monitor-state.json"
    _ = state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    config_path = root / "monitor-config.yaml"
    _ = config_path.write_text(
        """interval_seconds: 60
history:
  retention_days: 14
inventory:
  version: 1
  reviewed_at: '2026-08-26'
  authoritative_sources: [browser fixture]
domain_groups:
  core:
    label: PitchAI core
    description: Primary platform routes
    order: 10
domains:
  - domain: a.example
    label: Primary test route
    group: core
    environment: production
    kind: application
    sources: [browser fixture]
""",
        encoding="utf-8",
    )
    return state_path, config_path


def _settings(root: Path, state_path: Path, config_path: Path) -> RegistrySettings:
    artifacts_dir = root / "artifacts"
    tests_dir = root / "submitted-tests"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    return dashboard_registry_settings(
        DashboardSettingsInput(
            paths=RegistryPaths(
                db_path=str(root / "e2e-registry.db"),
                artifacts_dir=str(artifacts_dir),
                tests_dir=str(tests_dir),
            ),
            tokens=RegistryTokens(
                admin_token=secrets.token_urlsafe(24),
                monitor_token=secrets.token_urlsafe(24),
                runner_token=secrets.token_urlsafe(24),
            ),
            state_path=str(state_path),
            config_path=str(config_path),
        ),
    )


def _wait_until_ready(server: uvicorn.Server) -> None:
    for _attempt in range(_START_ATTEMPTS):
        if server.started:
            return
        time.sleep(_START_RETRY_SECONDS)
    message = "registry dashboard fixture did not become healthy"
    raise RuntimeError(message)


def _ready_server(
    server: uvicorn.Server,
    base_url: str,
    monitor_token: str,
) -> Generator[DashboardServer]:
    """Wait for readiness and yield one server receipt.

    Yields:
        Connection details after the health route succeeds.
    """
    _wait_until_ready(server)
    yield DashboardServer(base_url=base_url, monitor_token=monitor_token)


@contextmanager
def running_dashboard_server(root: Path) -> Generator[DashboardServer]:
    """Run one production-shaped registry server and restore global hooks.

    Yields:
        Connection details for the isolated server.

    Raises:
        RuntimeError: If the server cannot start or stop cleanly.
    """
    state_path, config_path = _write_monitor_fixture(root)
    settings = _settings(root, state_path, config_path)
    app = create_registry_app(settings)
    previous_builder = legacy_dashboard.build_dashboard_summary
    install_monitoring_v2(app)
    install_hotpath_monitoring(cast("HotpathApplication", cast("object", app)))
    port = free_tcp_port()
    server = uvicorn.Server(
        uvicorn.Config(
            cast("str", cast("object", app)),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        ),
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield from _ready_server(server, base_url, settings.monitor_token)
    finally:
        server.should_exit = True
        thread.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        legacy_dashboard.build_dashboard_summary = previous_builder
        if thread.is_alive():
            message = "registry dashboard fixture did not stop cleanly"
            raise RuntimeError(message)
