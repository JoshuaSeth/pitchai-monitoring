# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed shared helpers for live E2E registry acceptance tests."""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

from e2e_registry.models import parse_json_object, require_json_object, require_text

if TYPE_CHECKING:
    import httpx

    from e2e_registry.models import JsonObject, JsonValue

_HTTP_OK = 200


def base_url() -> str:
    """Return the explicitly configured registry URL or the production-host loopback edge."""
    return (
        os.getenv("E2E_REGISTRY_PUBLIC_BASE_URL")
        or os.getenv("E2E_REGISTRY_BASE_URL")
        or "http://127.0.0.1:8111"
    ).strip()


def admin_token() -> str:
    """Require the production registry administrator credential.

    Returns:
        The configured administrator bearer token.

    Raises:
        RuntimeError: If the credential is absent.
    """
    token = (os.getenv("E2E_REGISTRY_ADMIN_TOKEN") or "").strip()
    if not token:
        message = "Missing E2E_REGISTRY_ADMIN_TOKEN (export it or pass the env-file used by e2e-registry)"
        raise RuntimeError(message)
    return token


def response_payload(response: httpx.Response, *, label: str) -> JsonObject:
    """Require a successful response containing one JSON object.

    Returns:
        The validated response object.
    """
    response.raise_for_status()
    return parse_json_object(response.content, label=label)


def object_records(value: JsonValue, *, label: str) -> list[JsonObject]:
    """Validate an API collection without propagating untyped JSON values.

    Returns:
        The validated API records.

    Raises:
        TypeError: If the value is not a list.
    """
    if not isinstance(value, list):
        message = f"{label} must be a list"
        raise TypeError(message)
    return [require_json_object(item, label=f"{label} item") for item in value]


async def create_tenant_api_key(
    client: httpx.AsyncClient,
    *,
    registry_url: str,
    admin: str,
    tenant_name: str,
    key_name: str,
) -> str:
    """Create a tenant and return its sole acceptance-test API key.

    Returns:
        The newly created tenant API token.
    """
    tenant_payload = response_payload(
        await client.post(
            f"{registry_url.rstrip('/')}/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {admin}"},
            json={"name": tenant_name},
            timeout=15.0,
        ),
        label="live tenant response",
    )
    tenant = require_json_object(tenant_payload.get("tenant"), label="live tenant")
    tenant_id = require_text(tenant.get("id"), label="live tenant id")
    key_payload = response_payload(
        await client.post(
            f"{registry_url.rstrip('/')}/api/v1/admin/api_keys",
            headers={"Authorization": f"Bearer {admin}"},
            json={"tenant_id": tenant_id, "name": key_name},
            timeout=15.0,
        ),
        label="live API key response",
    )
    return require_text(key_payload.get("token"), label="live tenant token")


async def poll_for_completed_run(
    client: httpx.AsyncClient,
    *,
    registry_url: str,
    tenant_token: str,
    test_id: str,
    timeout_seconds: float = 240.0,
) -> JsonObject:
    """Poll past the runner's explicit pending placeholder to a completed run.

    Returns:
        The first completed run record.

    Raises:
        AssertionError: If no run completes before the deadline.
    """
    deadline = time.time() + timeout_seconds
    last: JsonObject | None = None
    while time.time() < deadline:
        payload = response_payload(
            await client.get(
                f"{registry_url.rstrip('/')}/api/v1/tests/{test_id}/runs",
                headers={"Authorization": f"Bearer {tenant_token}"},
                timeout=15.0,
            ),
            label="live run collection",
        )
        runs = object_records(payload.get("runs"), label="live runs")
        if runs:
            last = runs[0]
            error_kind = str(last.get("error_kind") or "").strip().lower()
            if last.get("finished_at_ts") is not None and error_kind != "pending":
                return last
        await asyncio.sleep(2.0)
    message = f"Timed out waiting for run completion test_id={test_id} last={last!r}"
    raise AssertionError(message)


async def verify_failure_artifacts(
    client: httpx.AsyncClient,
    *,
    registry_url: str,
    tenant_token: str,
    run_id: str,
) -> None:
    """Verify the live failure manifest and downloadable PNG signature.

    Raises:
        AssertionError: If artifacts are absent, inaccessible, or invalid.
    """
    detail_payload = response_payload(
        await client.get(
            f"{registry_url.rstrip('/')}/api/v1/runs/{run_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=20.0,
        ),
        label="failing live run detail",
    )
    run = require_json_object(detail_payload.get("run"), label="failing live run")
    artifacts_json = require_text(
        run.get("artifacts_json"), label="failing live run artifacts",
    )
    artifacts = parse_json_object(artifacts_json, label="failing live run artifacts")
    if artifacts.get("failure_screenshot") != "failure.png":
        message = "failure screenshot is missing from the artifact manifest"
        raise AssertionError(message)
    if artifacts.get("run_log") != "run.log":
        message = "run log is missing from the artifact manifest"
        raise AssertionError(message)

    response = await client.get(
        f"{registry_url.rstrip('/')}/api/v1/runs/{run_id}/artifacts/failure.png",
        headers={"Authorization": f"Bearer {tenant_token}"},
        timeout=30.0,
    )
    if response.status_code != _HTTP_OK:
        message = f"failure screenshot returned HTTP {response.status_code}"
        raise AssertionError(message)
    if response.content[:8] != b"\x89PNG\r\n\x1a\n":
        message = "failure screenshot does not have a PNG signature"
        raise AssertionError(message)
