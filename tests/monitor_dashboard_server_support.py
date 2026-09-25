# Copyright (c) 2026 PitchAI. All rights reserved.
"""Live server fixture for monitoring dashboard browser tests."""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import uvicorn
import yaml

from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings
from tests.monitor_dashboard_fixture_data import (
    dashboard_monitor_config,
    dashboard_monitor_state,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_HTTP_OK = 200


@dataclass(frozen=True)
class DashboardServer:
    """Address and monitor credential for one isolated registry server."""

    base_url: str
    monitor_token: str


def _pick_free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        _host, port = cast("tuple[str, int]", listener.getsockname())
        return port


def _registry_is_healthy(client: httpx.Client, *, server_url: str) -> bool:
    try:
        response = client.get(f"{server_url}/health", timeout=1.0)
    except httpx.HTTPError:
        return False
    return response.status_code == _HTTP_OK


@pytest.fixture
def dashboard_server(tmp_path: Path) -> Iterator[DashboardServer]:
    """Run an isolated dashboard server for browser acceptance checks.

    Yields:
        The running server address and monitoring token.

    Raises:
        RuntimeError: If the registry server does not become healthy.
    """
    db_path = tmp_path / "e2e-registry.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tests_dir = tmp_path / "submitted-tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    monitor_state = tmp_path / "monitor_state.json"
    monitor_cfg = tmp_path / "monitor_config.yaml"
    monitor_state.write_text(
        json.dumps(
            dashboard_monitor_state(time.time()),
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monitor_cfg.write_text(
        yaml.safe_dump(dashboard_monitor_config(), sort_keys=False),
        encoding="utf-8",
    )
    settings = RegistrySettings(
        db_path=str(db_path),
        artifacts_dir=str(artifacts_dir),
        tests_dir=str(tests_dir),
        admin_token=uuid.uuid4().hex,
        monitor_token=uuid.uuid4().hex,
        runner_token=uuid.uuid4().hex,
        alerts_enabled=False,
        dispatch_enabled=False,
        public_base_url="",
        monitor_state_path=str(monitor_state),
        monitor_config_path=str(monitor_cfg),
        dashboard_max_points=500,
    )
    port = _pick_free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        ),
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    server_url = f"http://127.0.0.1:{port}"
    with httpx.Client() as client:
        for _ in range(80):
            if _registry_is_healthy(client, server_url=server_url):
                break
            time.sleep(0.05)
        else:
            message = "registry server did not start"
            raise RuntimeError(message)

    try:
        yield DashboardServer(base_url=server_url, monitor_token=settings.monitor_token)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
