# Copyright (c) 2026 PitchAI. All rights reserved.
"""Real local HTTP fixtures for registry/runner integration tests."""

from __future__ import annotations

import socket
import threading
import time
import uuid
from dataclasses import dataclass
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import uvicorn

from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings
from tests.e2e_runner_isolation_support import traversable_root

if TYPE_CHECKING:
    from collections.abc import Iterator

_HTTP_OK = 200
_HOME_PAGE = (
    "<!doctype html><html><head><title>Home</title></head>"
    "<body><a href='/ok' id='oklink'>OK</a></body></html>"
)
_OK_PAGE = (
    "<!doctype html><html><head><title>OK Page</title></head>"
    "<body><nav>nav</nav><h1>Everything is fine</h1>"
    "<div id='items'><span class='item'>a</span><span class='item'>b</span></div></body></html>"
)


@dataclass(frozen=True)
class RegistryServer:
    """Address and settings for one live test registry."""

    base_url: str
    settings: RegistrySettings
    lease_directory: Path


def _pick_free_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        _host, port = cast("tuple[str, int]", server_socket.getsockname())
        return port


@pytest.fixture(scope="module")
def local_site_base_url() -> Iterator[str]:
    """Serve deterministic pages used by both submitted test runtimes.

    Yields:
        The local deterministic test-site URL.
    """
    with TemporaryDirectory(prefix="pitchai-e2e-site-") as site_directory:
        site_path = Path(site_directory)
        ok_directory = site_path / "ok"
        ok_directory.mkdir()
        _ = (site_path / "index.html").write_text(_HOME_PAGE, encoding="utf-8")
        _ = (ok_directory / "index.html").write_text(_OK_PAGE, encoding="utf-8")
        request_handler = partial(SimpleHTTPRequestHandler, directory=site_directory)
        http_server = HTTPServer(("127.0.0.1", 0), request_handler)
        host, port = cast("tuple[str, int]", http_server.server_address)
        thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://{host}:{port}"
        finally:
            http_server.shutdown()
            thread.join(timeout=5)
            http_server.server_close()


def _wait_for_registry(base_url: str) -> None:
    with httpx.Client() as client:
        for _attempt in range(80):
            try:
                response = client.get(f"{base_url}/health", timeout=1.0)
            except (httpx.HTTPError, OSError):
                time.sleep(0.05)
                continue
            if response.status_code == _HTTP_OK:
                return
            time.sleep(0.05)
    message = "registry server did not start"
    raise RuntimeError(message)


@pytest.fixture
def registry_server() -> Iterator[RegistryServer]:
    """Start a real registry with migrated private data and artifact roots.

    Yields:
        The running local registry and its resolved settings.
    """
    with (
        traversable_root("pitchai-e2e-registry-data-") as data_root,
        traversable_root("pitchai-e2e-registry-artifacts-") as artifacts_root,
        traversable_root("pitchai-e2e-runner-leases-") as lease_root,
    ):
        admin_token = uuid.uuid4().hex
        monitor_token = uuid.uuid4().hex
        runner_token = uuid.uuid4().hex
        settings = RegistrySettings(
            db_path=str(data_root / "e2e-registry.db"),
            artifacts_dir=str(artifacts_root),
            tests_dir=str(data_root / "submitted-tests"),
            admin_token=admin_token,
            monitor_token=monitor_token,
            runner_token=runner_token,
            alerts_enabled=False,
            dispatch_enabled=False,
            public_base_url="",
        )
        application = create_app(settings)
        port = _pick_free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
            ),
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_registry(base_url)
        try:
            yield RegistryServer(
                base_url=base_url,
                settings=settings,
                lease_directory=lease_root / "locks",
            )
        finally:
            server.should_exit = True
            thread.join(timeout=5)
