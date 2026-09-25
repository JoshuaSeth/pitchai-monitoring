# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed API and subprocess helpers for registry/runner integration."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from e2e_registry.models import parse_json_object, require_json_object, require_text
from tests.e2e_registry_runner_sources import FAILING_JAVASCRIPT_SOURCE, PASSING_PYTHON_SOURCE
from tests.e2e_runner_topology import (
    UnsupportedSandboxRuntimeTopologyError,
    sandbox_runtime_topology_issue,
)

if TYPE_CHECKING:
    from e2e_registry.models import JsonObject, JsonValue
    from tests.e2e_registry_server_support import RegistryServer


@dataclass(frozen=True)
class RegisteredScenario:
    """Registry identities and tests participating in the integration flow."""

    server: RegistryServer
    tenant_token: str
    passing_test_id: str
    failing_test_id: str


@dataclass(frozen=True)
class _UploadedTest:
    scenario_name: str
    site_url: str
    kind: str
    filename: str
    source: str


def json_payload(response: httpx.Response, *, label: str) -> JsonObject:
    """Decode one integration response through the production JSON contract.

    Returns:
        The validated response object.
    """
    _ = response.raise_for_status()
    return parse_json_object(response.content, label=label)


def json_records(value: JsonValue, *, label: str) -> list[JsonObject]:
    """Validate a list of API records without allowing implicit ``Any``.

    Returns:
        The validated response records.

    Raises:
        TypeError: If the response value is not a list.
    """
    if not isinstance(value, list):
        message = f"{label} must be a list"
        raise TypeError(message)
    return [require_json_object(item, label=f"{label} item") for item in value]


def _tenant_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _upload_test(
    client: httpx.AsyncClient,
    *,
    uploaded_test: _UploadedTest,
    tenant_token: str,
) -> str:
    response = await client.post(
        "/api/v1/tests/upload",
        headers=_tenant_headers(tenant_token),
        data={
            "name": uploaded_test.scenario_name,
            "base_url": uploaded_test.site_url,
            "kind": uploaded_test.kind,
            "interval_seconds": "3600",
            "timeout_seconds": "15",
            "jitter_seconds": "0",
            "down_after_failures": "1",
            "up_after_successes": "1",
            "notify_on_recovery": "0",
            "dispatch_on_failure": "0",
        },
        files={
            "file": (
                uploaded_test.filename,
                uploaded_test.source.encode(),
                "application/octet-stream",
            ),
        },
        timeout=20.0,
    )
    payload = json_payload(response, label=f"{uploaded_test.scenario_name} upload")
    test = require_json_object(payload.get("test"), label="uploaded test")
    return require_text(test.get("id"), label="uploaded test id")


async def register_scenario(
    server: RegistryServer,
    *,
    site_url: str,
) -> RegisteredScenario:
    """Create the tenant and one passing/one failing submitted test.

    Returns:
        The registered tenant and test identities.
    """
    async with httpx.AsyncClient(base_url=server.base_url) as client:
        tenant_payload = json_payload(
            await client.post(
                "/api/v1/admin/tenants",
                headers=_tenant_headers(server.settings.admin_token),
                json={"name": "external-dev-tenant"},
                timeout=5.0,
            ),
            label="tenant response",
        )
        tenant = require_json_object(tenant_payload.get("tenant"), label="tenant")
        tenant_id = require_text(tenant.get("id"), label="tenant id")
        key_payload = json_payload(
            await client.post(
                "/api/v1/admin/api_keys",
                headers=_tenant_headers(server.settings.admin_token),
                json={"tenant_id": tenant_id, "name": "dev-key"},
                timeout=5.0,
            ),
            label="API key response",
        )
        tenant_token = require_text(key_payload.get("token"), label="tenant token")
        passing_test_id = await _upload_test(
            client,
            uploaded_test=_UploadedTest(
                scenario_name="pass_local_py",
                site_url=site_url,
                kind="playwright_python",
                filename="pass_test.py",
                source=PASSING_PYTHON_SOURCE,
            ),
            tenant_token=tenant_token,
        )
        failing_test_id = await _upload_test(
            client,
            uploaded_test=_UploadedTest(
                scenario_name="fail_local_js",
                site_url=site_url,
                kind="puppeteer_js",
                filename="fail_test.js",
                source=FAILING_JAVASCRIPT_SOURCE,
            ),
            tenant_token=tenant_token,
        )
    return RegisteredScenario(server, tenant_token, passing_test_id, failing_test_id)


async def run_runner_once(
    scenario: RegisteredScenario, *, chromium_path: str, timeout_seconds: int,
) -> None:
    """Execute one real runner batch and require a clean supervisor exit.

    Raises:
        UnsupportedSandboxRuntimeTopologyError: If a dropped UID cannot enter the
            local interpreter or working directory.
        RuntimeError: If the runner times out or exits unsuccessfully.
    """
    topology_issue = sandbox_runtime_topology_issue()
    if topology_issue is not None:
        raise UnsupportedSandboxRuntimeTopologyError(topology_issue)
    environment = os.environ.copy()
    environment.update(
        {
            "CHROMIUM_PATH": chromium_path,
            "E2E_REGISTRY_BASE_URL": scenario.server.base_url,
            "E2E_REGISTRY_RUNNER_TOKEN": scenario.server.settings.runner_token,
            "E2E_ARTIFACTS_DIR": scenario.server.settings.artifacts_dir,
            "E2E_TESTS_DIR": scenario.server.settings.tests_dir,
            "E2E_SANDBOX_UID_LEASE_DIR": str(scenario.server.lease_directory),
            "E2E_RUNNER_CONCURRENCY": "1",
            "E2E_RUNNER_TRACE_ON_FAILURE": "0",
        },
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "e2e_runner.main",
        "--once",
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=Path.cwd(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        process.kill()
        _ = await process.wait()
        message = "runner timed out"
        raise RuntimeError(message) from exc
    if process.returncode != 0:
        message = f"runner failed:\nSTDOUT:\n{stdout.decode()}\nSTDERR:\n{stderr.decode()}"
        raise RuntimeError(message)


def tenant_headers(scenario: RegisteredScenario) -> dict[str, str]:
    """Return tenant authorization for scenario API requests.

    Returns:
        The tenant bearer authorization header.
    """
    return _tenant_headers(scenario.tenant_token)
