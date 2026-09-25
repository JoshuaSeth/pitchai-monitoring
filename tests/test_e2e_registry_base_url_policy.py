# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry base-URL allowlist policy tests."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from e2e_registry.app import create_app
from e2e_registry.app_policy import load_monitored_allowlist_hosts
from e2e_registry.models import parse_json_object, require_json_object, require_text
from e2e_registry.settings import RegistrySettings

_HTTP_OK = 200
_HTTP_BAD_REQUEST = 400
_EXPECTED_PRODUCTION_HOSTS = 58


def _bootstrap_client(tmp_path: Path) -> tuple[TestClient, str]:
    settings = RegistrySettings(
        db_path=str(tmp_path / "e2e-registry.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
        tests_dir=str(tmp_path / "submitted-tests"),
        admin_token=uuid.uuid4().hex,
        monitor_token=uuid.uuid4().hex,
        runner_token=uuid.uuid4().hex,
        alerts_enabled=False,
        dispatch_enabled=False,
        strict_base_url_policy=True,
        base_url_allowed_hosts=("autopar.pitchai.net", "deplanbook.com", "cms.deplanbook.com"),
        base_url_allow_monitored_domains=False,
        public_base_url="https://monitoring.pitchai.net",
    )
    app = create_app(settings)
    client = TestClient(app)

    tenant_response = client.post(
        "/api/v1/admin/tenants",
        headers={"Authorization": f"Bearer {settings.admin_token}"},
        json={"name": "policy-tenant"},
    )
    if tenant_response.status_code != _HTTP_OK:
        message = f"tenant bootstrap returned HTTP {tenant_response.status_code}"
        raise AssertionError(message)
    tenant_payload = parse_json_object(tenant_response.content, label="policy tenant")
    tenant = require_json_object(tenant_payload.get("tenant"), label="policy tenant")
    tenant_id = require_text(tenant.get("id"), label="policy tenant id")

    key_response = client.post(
        "/api/v1/admin/api_keys",
        headers={"Authorization": f"Bearer {settings.admin_token}"},
        json={"tenant_id": tenant_id, "name": "policy-key"},
    )
    if key_response.status_code != _HTTP_OK:
        message = f"API key bootstrap returned HTTP {key_response.status_code}"
        raise AssertionError(message)
    key_payload = parse_json_object(key_response.content, label="policy API key")
    tenant_token = require_text(key_payload.get("token"), label="policy tenant token")
    return client, tenant_token


def _simple_playwright_py() -> bytes:
    return (
        b"async def run(page, base_url, artifacts_dir):\n"
        b"    await page.goto(base_url.rstrip('/') + '/', wait_until='domcontentloaded')\n"
    )


def test_production_inventory_expands_e2e_allowlist_and_excludes_retired_domains() -> None:
    """Include active production hosts while excluding retired inventory.

    Raises:
        AssertionError: If the production allowlist diverges from inventory policy.
    """
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    settings = RegistrySettings(
        base_url_allow_monitored_domains=True,
        monitor_config_path=str(config_path),
    )

    hosts = load_monitored_allowlist_hosts(settings)

    if len(hosts) != _EXPECTED_PRODUCTION_HOSTS:
        message = f"expected 58 production hosts, got {len(hosts)}"
        raise AssertionError(message)
    required_hosts = {
        "formatief-toetsen.pitchai.net",
        "staging.formatief-toetsen.pitchai.net",
        "dft-marketing-staging.pitchai.net",
    }
    missing_hosts = required_hosts - hosts
    if missing_hosts:
        message = f"production allowlist omitted active hosts: {sorted(missing_hosts)!r}"
        raise AssertionError(message)
    retired_hosts = {"n8n.pitchai.net", "quickchat.pitchai.net"} & hosts
    if retired_hosts:
        message = f"production allowlist retained retired hosts: {sorted(retired_hosts)!r}"
        raise AssertionError(message)


def test_upload_rejects_reserved_example_domain(tmp_path: Path) -> None:
    """Reject the reserved example.com target under strict policy.

    Raises:
        AssertionError: If upload accepts the target or returns the wrong reason.
    """
    client, tenant_token = _bootstrap_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": "bad_example_domain",
                "base_url": "https://example.com",
                "kind": "playwright_python",
                "interval_seconds": "300",
                "timeout_seconds": "45",
                "jitter_seconds": "0",
                "down_after_failures": "2",
                "up_after_successes": "2",
            },
            files={"file": ("test.py", _simple_playwright_py(), "text/x-python")},
        )
    if response.status_code != _HTTP_BAD_REQUEST:
        message = f"reserved-domain upload returned HTTP {response.status_code}"
        raise AssertionError(message)
    payload = parse_json_object(response.content, label="reserved-domain rejection")
    if payload.get("detail") != "base_url_not_allowed_host":
        message = f"unexpected reserved-domain rejection: {payload!r}"
        raise AssertionError(message)


def test_upload_rejects_non_allowlisted_domain_when_strict(tmp_path: Path) -> None:
    """Reject a non-monitored PitchAI host under strict policy.

    Raises:
        AssertionError: If upload accepts the target or returns the wrong reason.
    """
    client, tenant_token = _bootstrap_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": "bad_unlisted_domain",
                "base_url": "https://not-allowlisted.pitchai.net",
                "kind": "playwright_python",
                "interval_seconds": "300",
                "timeout_seconds": "45",
                "jitter_seconds": "0",
                "down_after_failures": "2",
                "up_after_successes": "2",
            },
            files={"file": ("test.py", _simple_playwright_py(), "text/x-python")},
        )
    if response.status_code != _HTTP_BAD_REQUEST:
        message = f"non-allowlisted upload returned HTTP {response.status_code}"
        raise AssertionError(message)
    payload = parse_json_object(response.content, label="non-allowlisted rejection")
    if payload.get("detail") != "base_url_not_monitored_domain":
        message = f"unexpected non-allowlisted rejection: {payload!r}"
        raise AssertionError(message)


def test_upload_accepts_allowlisted_domain_and_patch_rejects_reserved(tmp_path: Path) -> None:
    """Accept an allowlisted upload but reject a reserved-host patch.

    Raises:
        AssertionError: If either URL policy outcome is incorrect.
    """
    client, tenant_token = _bootstrap_client(tmp_path)
    with client:
        upload_response = client.post(
            "/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": "allowed_domain",
                "base_url": "https://autopar.pitchai.net",
                "kind": "playwright_python",
                "interval_seconds": "300",
                "timeout_seconds": "45",
                "jitter_seconds": "0",
                "down_after_failures": "2",
                "up_after_successes": "2",
            },
            files={"file": ("test.py", _simple_playwright_py(), "text/x-python")},
        )
        if upload_response.status_code != _HTTP_OK:
            message = f"allowlisted upload returned HTTP {upload_response.status_code}"
            raise AssertionError(message)
        upload_payload = parse_json_object(
            upload_response.content,
            label="allowlisted upload",
        )
        uploaded_test = require_json_object(
            upload_payload.get("test"),
            label="allowlisted uploaded test",
        )
        test_id = require_text(uploaded_test.get("id"), label="allowlisted test id")

        patch_response = client.patch(
            f"/api/v1/tests/{test_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"base_url": "https://example.com"},
        )
    if patch_response.status_code != _HTTP_BAD_REQUEST:
        message = f"reserved-host patch returned HTTP {patch_response.status_code}"
        raise AssertionError(message)
    patch_payload = parse_json_object(patch_response.content, label="URL patch rejection")
    if patch_payload.get("detail") != "base_url_not_allowed_host":
        message = f"unexpected reserved-host patch rejection: {patch_payload!r}"
        raise AssertionError(message)
