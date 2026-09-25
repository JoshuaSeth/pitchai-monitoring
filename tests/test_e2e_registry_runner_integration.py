# Copyright (c) 2026 PitchAI. All rights reserved.
"""End-to-end integration of registry APIs, real runner, and browser runtimes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.common_check import find_chromium_executable
from e2e_registry.models import (
    parse_json_object,
    require_integer,
    require_json_object,
    require_text,
)
from tests.e2e_registry_runner_sources import RECOVERED_JAVASCRIPT_SOURCE
from tests.e2e_registry_runner_support import (
    json_payload,
    json_records,
    register_scenario,
    run_runner_once,
    tenant_headers,
)
from tests.e2e_runner_topology import sandbox_runtime_topology_issue

if TYPE_CHECKING:
    from e2e_registry.models import JsonObject
    from tests.e2e_registry_runner_support import RegisteredScenario
    from tests.e2e_registry_server_support import RegistryServer

pytest_plugins = ["tests.e2e_registry_server_support"]
_MINIMUM_REGISTERED_TESTS = 2
_HTTP_OK = 200


async def _run_records(
    client: httpx.AsyncClient,
    scenario: RegisteredScenario,
    test_id: str,
) -> list[JsonObject]:
    payload = json_payload(
        await client.get(
            f"/api/v1/tests/{test_id}/runs",
            headers=tenant_headers(scenario),
            timeout=10.0,
        ),
        label="test runs",
    )
    return json_records(payload.get("runs"), label="test runs")


async def _verify_initial_results(scenario: RegisteredScenario) -> int:
    async with httpx.AsyncClient(base_url=scenario.server.base_url) as client:
        summary = json_payload(
            await client.get(
                "/api/v1/status/summary",
                headers={"Authorization": f"Bearer {scenario.server.settings.monitor_token}"},
                timeout=10.0,
            ),
            label="status summary",
        )
        if summary.get("ok") is not True:
            message = "registry status summary is not healthy"
            raise AssertionError(message)
        total_tests = require_integer(summary.get("total_tests"), label="total tests")
        if total_tests < _MINIMUM_REGISTERED_TESTS:
            message = f"registry summary contains only {total_tests} tests"
            raise AssertionError(message)
        failing_tests = require_integer(summary.get("failing_tests"), label="failing tests")
        if failing_tests < 1:
            message = "registry summary contains no failing test"
            raise AssertionError(message)
        passing_runs = await _run_records(client, scenario, scenario.passing_test_id)
        if not passing_runs:
            message = "passing scenario produced no run"
            raise AssertionError(message)
        if passing_runs[0].get("status") != "pass":
            passing_run_id = require_text(passing_runs[0].get("id"), label="passing run id")
            output_response = await client.get(
                f"/api/v1/runs/{passing_run_id}/artifacts/runner_output.log",
                headers=tenant_headers(scenario),
                timeout=10.0,
            )
            message = (
                f"passing scenario returned {passing_runs[0].get('status')!r}; "
                f"error_kind={passing_runs[0].get('error_kind')!r}; "
                f"error_message={passing_runs[0].get('error_message')!r}; "
                f"runner_output={output_response.text!r}"
            )
            raise AssertionError(message)
        failing_runs = await _run_records(client, scenario, scenario.failing_test_id)
        if not failing_runs:
            message = "failing scenario produced no run"
            raise AssertionError(message)
        if failing_runs[0].get("status") not in {"fail", "infra_degraded"}:
            message = f"failing scenario returned {failing_runs[0].get('status')!r}"
            raise AssertionError(message)
        failing_run_id = require_text(failing_runs[0].get("id"), label="failing run id")
        run_payload = json_payload(
            await client.get(
                f"/api/v1/runs/{failing_run_id}",
                headers=tenant_headers(scenario),
                timeout=10.0,
            ),
            label="failing run",
        )
        run = require_json_object(run_payload.get("run"), label="run")
        if run.get("status") == "fail":
            artifacts = parse_json_object(
                run.get("artifacts_json"),
                label="run artifacts",
                empty_when_missing=True,
            )
            output_response = await client.get(
                f"/api/v1/runs/{failing_run_id}/artifacts/runner_output.log",
                headers=tenant_headers(scenario),
                timeout=10.0,
            )
            if artifacts.get("failure_screenshot") != "failure.png":
                message = (
                    "failure run omitted its screenshot manifest entry; "
                    f"error_kind={run.get('error_kind')!r}; "
                    f"error_message={run.get('error_message')!r}; "
                    f"artifacts={artifacts!r}; runner_output={output_response.text!r}"
                )
                raise AssertionError(message)
            if artifacts.get("run_log") != "run.log":
                message = "failure run omitted its log manifest entry"
                raise AssertionError(message)
            artifact_response = await client.get(
                f"/api/v1/runs/{failing_run_id}/artifacts/failure.png",
                headers=tenant_headers(scenario),
                timeout=20.0,
            )
            if artifact_response.status_code != _HTTP_OK:
                message = f"failure screenshot returned HTTP {artifact_response.status_code}"
                raise AssertionError(message)
        return len(failing_runs)


async def _disable_and_trigger(scenario: RegisteredScenario) -> None:
    async with httpx.AsyncClient(base_url=scenario.server.base_url) as client:
        _ = json_payload(
            await client.post(
                f"/api/v1/tests/{scenario.failing_test_id}/disable",
                headers=tenant_headers(scenario),
                json={"reason": "temporary disable", "until": time.time() + 3600},
                timeout=10.0,
            ),
            label="disable response",
        )
        _ = json_payload(
            await client.post(
                f"/api/v1/tests/{scenario.failing_test_id}/run",
                headers=tenant_headers(scenario),
                timeout=10.0,
            ),
            label="disabled trigger response",
        )


async def _recover_failing_test(scenario: RegisteredScenario) -> None:
    async with httpx.AsyncClient(base_url=scenario.server.base_url) as client:
        _ = json_payload(
            await client.post(
                f"/api/v1/tests/{scenario.failing_test_id}/enable",
                headers=tenant_headers(scenario),
                timeout=10.0,
            ),
            label="enable response",
        )
        _ = json_payload(
            await client.post(
                f"/api/v1/tests/{scenario.failing_test_id}/source",
                headers=tenant_headers(scenario),
                files={
                    "file": (
                        "pass_test.js",
                        RECOVERED_JAVASCRIPT_SOURCE.encode(),
                        "application/javascript",
                    ),
                },
                timeout=20.0,
            ),
            label="source replacement response",
        )
        _ = json_payload(
            await client.post(
                f"/api/v1/tests/{scenario.failing_test_id}/run",
                headers=tenant_headers(scenario),
                timeout=10.0,
            ),
            label="recovery trigger response",
        )


@pytest.mark.asyncio
async def test_e2e_registry_and_runner_end_to_end(
    registry_server: RegistryServer,
    local_site_base_url: str,
) -> None:
    """Exercise pass, artifacts, disablement, and recovery through live HTTP.

    Raises:
        AssertionError: If disablement or recovery violates its API contract.
    """
    topology_issue = sandbox_runtime_topology_issue()
    if topology_issue is not None:
        pytest.xfail(topology_issue)
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")
    scenario = await register_scenario(registry_server, site_url=local_site_base_url)
    await run_runner_once(scenario, chromium_path=chromium_path, timeout_seconds=180)
    await run_runner_once(scenario, chromium_path=chromium_path, timeout_seconds=180)
    initial_failure_runs = await _verify_initial_results(scenario)

    await _disable_and_trigger(scenario)
    await run_runner_once(scenario, chromium_path=chromium_path, timeout_seconds=120)
    async with httpx.AsyncClient(base_url=scenario.server.base_url) as client:
        disabled_run_count = len(await _run_records(client, scenario, scenario.failing_test_id))
        if disabled_run_count != initial_failure_runs:
            message = "disabled test unexpectedly produced another run"
            raise AssertionError(message)

    await _recover_failing_test(scenario)
    await run_runner_once(scenario, chromium_path=chromium_path, timeout_seconds=180)
    async with httpx.AsyncClient(base_url=scenario.server.base_url) as client:
        test_payload = json_payload(
            await client.get(
                f"/api/v1/tests/{scenario.failing_test_id}",
                headers=tenant_headers(scenario),
                timeout=10.0,
            ),
            label="recovered test",
        )
    recovered_test = require_json_object(test_payload.get("test"), label="recovered test")
    effective_health = require_integer(recovered_test.get("effective_ok"), label="effective health")
    if effective_health != 1:
        message = f"recovered test effective health is {effective_health}"
        raise AssertionError(message)
