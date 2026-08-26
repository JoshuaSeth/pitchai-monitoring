# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed helpers for E2E registry base-URL policy tests."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from fastapi.testclient import TestClient

from domain_checks.monitoring_contracts.json_types import json_object, text_value
from e2e_registry.monitoring_v2.legacy import (
    PolicySettingsInput,
    RegistryPaths,
    RegistryTokens,
    create_registry_app,
    policy_registry_settings,
)
from monitoring_test_support.inventory import CONFIG_PATH

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import Response

    from domain_checks.monitoring_contracts.json_types import JsonInput, JsonObject

_HTTP_OK = 200
_SOURCE = (
    b"async def run(page, base_url, artifacts_dir):\n"
    b"    await page.goto(base_url.rstrip('/') + '/', wait_until='domcontentloaded')\n"
)


@dataclass(frozen=True)
class PolicyClient:
    """Authenticated test client for one isolated registry database."""

    client: TestClient
    tenant_token: str


def response_object(response: Response) -> JsonObject:
    """Decode an HTTP response through the strict JSON boundary.

    Returns:
        The normalized response object.
    """
    return json_object(cast("JsonInput", json.loads(response.text)))


def bootstrap_policy_client(root: Path, *, allow_monitored_domains: bool) -> PolicyClient:
    """Create one strict-policy registry and tenant API key.

    Returns:
        An authenticated client bound to the isolated registry.

    Raises:
        RuntimeError: If registry bootstrap does not return valid credentials.
    """
    admin_token = secrets.token_urlsafe(24)
    explicit_hosts = ()
    if not allow_monitored_domains:
        explicit_hosts = ("autopar.pitchai.net", "deplanbook.com", "cms.deplanbook.com")
    settings = policy_registry_settings(
        PolicySettingsInput(
            paths=RegistryPaths(
                db_path=str(root / "e2e-registry.db"),
                artifacts_dir=str(root / "artifacts"),
                tests_dir=str(root / "submitted-tests"),
            ),
            tokens=RegistryTokens(
                admin_token=admin_token,
                monitor_token=secrets.token_urlsafe(24),
                runner_token=secrets.token_urlsafe(24),
            ),
            explicit_hosts=explicit_hosts,
            allow_monitored_domains=allow_monitored_domains,
            monitor_config_path=str(CONFIG_PATH),
        ),
    )
    client = TestClient(create_registry_app(settings))
    tenant_response = client.post(
        "/api/v1/admin/tenants",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "policy-tenant"},
    )
    if tenant_response.status_code != _HTTP_OK:
        message = f"could not create base-URL policy tenant: {tenant_response.text}"
        raise RuntimeError(message)
    tenant = json_object(response_object(tenant_response).get("tenant"))
    tenant_id = text_value(tenant.get("id"))
    key_response = client.post(
        "/api/v1/admin/api_keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"tenant_id": tenant_id, "name": "policy-key"},
    )
    if key_response.status_code != _HTTP_OK:
        message = f"could not create base-URL policy key: {key_response.text}"
        raise RuntimeError(message)
    tenant_token = text_value(response_object(key_response).get("token"))
    if not tenant_token:
        message = "base-URL policy API key response omitted its token"
        raise RuntimeError(message)
    return PolicyClient(client=client, tenant_token=tenant_token)


def upload_browser_test(policy: PolicyClient, *, name: str, base_url: str) -> Response:
    """Upload one minimal browser test through the public registry API.

    Returns:
        The registry response.
    """
    return policy.client.post(
        "/api/v1/tests/upload",
        headers={"Authorization": f"Bearer {policy.tenant_token}"},
        data={
            "name": name,
            "base_url": base_url,
            "kind": "playwright_python",
            "interval_seconds": "300",
            "timeout_seconds": "45",
            "jitter_seconds": "0",
            "down_after_failures": "2",
            "up_after_successes": "2",
        },
        files={"file": ("test.py", _SOURCE, "text/x-python")},
    )


def patch_test_base_url(policy: PolicyClient, *, test_id: str, base_url: str) -> Response:
    """Patch one registered test's base URL.

    Returns:
        The registry response.
    """
    return policy.client.patch(
        f"/api/v1/tests/{test_id}",
        headers={"Authorization": f"Bearer {policy.tenant_token}"},
        json={"base_url": base_url},
    )
