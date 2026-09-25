# Copyright (c) 2026 PitchAI. All rights reserved.
"""Live E2E registry API acceptance workflow."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

import httpx

from e2e_registry.models import require_json_object, require_text
from tests.live_e2e_registry_actions import disable_test, run_count, trigger_test
from tests.live_e2e_registry_sources import COMMON_CONFIG, FAILING_SOURCE, PASSING_SOURCE
from tests.live_e2e_registry_support import (
    admin_token,
    base_url,
    create_tenant_api_key,
    object_records,
    poll_for_completed_run,
    response_payload,
    verify_failure_artifacts,
)

_HTTP_NOT_FOUND = 404


@dataclass(frozen=True)
class _UploadRequest:
    name: str
    kind: str
    source: str
    filename: str
    content_type: str


@dataclass(frozen=True)
class _LiveScenario:
    registry_url: str
    admin: str
    tenant_token: str
    passing_id: str
    failing_id: str
    nonce: str


async def _upload_test(
    client: httpx.AsyncClient,
    *,
    registry_url: str,
    tenant_token: str,
    upload: _UploadRequest,
) -> str:
    configuration: dict[str, str] = {}
    for key, value in COMMON_CONFIG.items():
        configuration[key] = str(value)
    payload = response_payload(
        await client.post(
            f"{registry_url.rstrip('/')}/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": upload.name,
                "base_url": "https://deplanbook.com",
                "kind": upload.kind,
                **configuration,
            },
            files={"file": (upload.filename, upload.source.encode(), upload.content_type)},
            timeout=60.0,
        ),
        label=f"{upload.name} upload",
    )
    test = require_json_object(payload.get("test"), label="uploaded live test")
    return require_text(test.get("id"), label="uploaded live test id")


async def _create_live_scenario(client: httpx.AsyncClient) -> _LiveScenario:
    registry_url = base_url()
    admin = admin_token()
    nonce = uuid.uuid4().hex[:8]
    tenant_token = await create_tenant_api_key(
        client,
        registry_url=registry_url,
        admin=admin,
        tenant_name=f"live-smoke-{uuid.uuid4().hex[:10]}",
        key_name="live-smoke-key",
    )
    passing_id = await _upload_test(
        client,
        registry_url=registry_url,
        tenant_token=tenant_token,
        upload=_UploadRequest(
            name=f"live_pass_{nonce}",
            kind="playwright_python",
            source=PASSING_SOURCE,
            filename="live_pass.py",
            content_type="text/x-python",
        ),
    )
    failing_id = await _upload_test(
        client,
        registry_url=registry_url,
        tenant_token=tenant_token,
        upload=_UploadRequest(
            name=f"live_fail_{nonce}",
            kind="puppeteer_js",
            source=FAILING_SOURCE,
            filename="live_fail.js",
            content_type="application/javascript",
        ),
    )
    return _LiveScenario(registry_url, admin, tenant_token, passing_id, failing_id, nonce)


async def _verify_live_execution(client: httpx.AsyncClient, scenario: _LiveScenario) -> str:
    for test_id in (scenario.passing_id, scenario.failing_id):
        await trigger_test(
            client,
            registry_url=scenario.registry_url,
            tenant_token=scenario.tenant_token,
            test_id=test_id,
        )
    passing_run = await poll_for_completed_run(
        client,
        registry_url=scenario.registry_url,
        tenant_token=scenario.tenant_token,
        test_id=scenario.passing_id,
        timeout_seconds=300.0,
    )
    if passing_run.get("status") != "pass":
        message = f"passing live test returned {passing_run.get('status')!r}"
        raise AssertionError(message)
    if passing_run.get("elapsed_ms") is None:
        message = "passing live run omitted elapsed time"
        raise AssertionError(message)
    failing_run = await poll_for_completed_run(
        client,
        registry_url=scenario.registry_url,
        tenant_token=scenario.tenant_token,
        test_id=scenario.failing_id,
        timeout_seconds=300.0,
    )
    if failing_run.get("status") != "fail":
        message = f"failing live test returned {failing_run.get('status')!r}"
        raise AssertionError(message)
    return require_text(failing_run.get("id"), label="failing live run id")


async def _verify_live_disablement(client: httpx.AsyncClient, scenario: _LiveScenario) -> float:
    before_count = await run_count(
        client,
        registry_url=scenario.registry_url,
        tenant_token=scenario.tenant_token,
        test_id=scenario.failing_id,
    )
    until_ts = time.time() + (10 * 365 * 24 * 3600)
    await disable_test(
        client,
        registry_url=scenario.registry_url,
        tenant_token=scenario.tenant_token,
        test_id=scenario.failing_id,
        disablement=("live smoke disable", until_ts),
    )
    await trigger_test(
        client,
        registry_url=scenario.registry_url,
        tenant_token=scenario.tenant_token,
        test_id=scenario.failing_id,
    )
    await asyncio.sleep(10.0)
    after_count = await run_count(
        client,
        registry_url=scenario.registry_url,
        tenant_token=scenario.tenant_token,
        test_id=scenario.failing_id,
    )
    if after_count != before_count:
        message = "disabled test unexpectedly created a new run"
        raise AssertionError(message)
    return until_ts


async def _verify_live_isolation_and_summary(
    client: httpx.AsyncClient,
    scenario: _LiveScenario,
) -> None:
    other_token = await create_tenant_api_key(
        client,
        registry_url=scenario.registry_url,
        admin=scenario.admin,
        tenant_name=f"live-iso-{uuid.uuid4().hex[:10]}",
        key_name="iso-key",
    )
    isolated = await client.get(
        f"{scenario.registry_url.rstrip('/')}/api/v1/tests/{scenario.passing_id}",
        headers={"Authorization": f"Bearer {other_token}"},
        timeout=15.0,
    )
    if isolated.status_code != _HTTP_NOT_FOUND:
        message = f"cross-tenant test lookup returned HTTP {isolated.status_code}"
        raise AssertionError(message)
    summary = response_payload(
        await client.get(
            f"{scenario.registry_url.rstrip('/')}/api/v1/status/summary",
            headers={"Authorization": f"Bearer {scenario.admin}"},
            timeout=15.0,
        ),
        label="live status summary",
    )
    if summary.get("ok") is not True:
        message = "live registry status summary is not healthy"
        raise AssertionError(message)
    missing_names = {f"live_pass_{scenario.nonce}", f"live_fail_{scenario.nonce}"}
    summary_tests = object_records(summary.get("tests"), label="summary tests")
    observed_names = {str(test.get("test_name") or "") for test in summary_tests}
    missing_names.difference_update(observed_names)
    if missing_names:
        message = f"status summary omitted live tests: {missing_names}"
        raise AssertionError(message)


async def run_live_api_acceptance() -> None:
    """Exercise pass/fail execution, artifacts, disable semantics, and isolation."""
    async with httpx.AsyncClient(
        headers={"User-Agent": "PitchAI Live E2E Registry Test"},
    ) as client:
        scenario = await _create_live_scenario(client)
        failing_run_id = await _verify_live_execution(client, scenario)
        await verify_failure_artifacts(
            client,
            registry_url=scenario.registry_url,
            tenant_token=scenario.tenant_token,
            run_id=failing_run_id,
        )
        until_ts = await _verify_live_disablement(client, scenario)
        await _verify_live_isolation_and_summary(client, scenario)
        await disable_test(
            client,
            registry_url=scenario.registry_url,
            tenant_token=scenario.tenant_token,
            test_id=scenario.passing_id,
            disablement=("live smoke cleanup", until_ts),
        )
