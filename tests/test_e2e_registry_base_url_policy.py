from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings


def _bootstrap_client(tmp_path: Path) -> tuple[TestClient, str]:
    settings = RegistrySettings(
        db_path=str(tmp_path / "e2e-registry.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
        tests_dir=str(tmp_path / "submitted-tests"),
        admin_token="adm_policy_token",
        monitor_token="mon_policy_token",
        runner_token="run_policy_token",
        alerts_enabled=False,
        dispatch_enabled=False,
        strict_base_url_policy=True,
        base_url_allowed_hosts=("autopar.pitchai.net", "deplanbook.com", "cms.deplanbook.com"),
        base_url_allow_monitored_domains=False,
        public_base_url="https://monitoring.pitchai.net",
    )
    app = create_app(settings)
    client = TestClient(app)

    r = client.post(
        "/api/v1/admin/tenants",
        headers={"Authorization": f"Bearer {settings.admin_token}"},
        json={"name": "policy-tenant"},
    )
    assert r.status_code == 200
    tenant_id = r.json()["tenant"]["id"]

    r = client.post(
        "/api/v1/admin/api_keys",
        headers={"Authorization": f"Bearer {settings.admin_token}"},
        json={"tenant_id": tenant_id, "name": "policy-key"},
    )
    assert r.status_code == 200
    tenant_token = r.json()["token"]
    return client, tenant_token


def _simple_playwright_py() -> bytes:
    return (
        "async def run(page, base_url, artifacts_dir):\n"
        "    await page.goto(base_url.rstrip('/') + '/', wait_until='domcontentloaded')\n"
    ).encode("utf-8")


def test_upload_rejects_reserved_example_domain(tmp_path: Path) -> None:
    client, tenant_token = _bootstrap_client(tmp_path)
    with client:
        r = client.post(
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
    assert r.status_code == 400
    assert r.json().get("detail") == "base_url_not_allowed_host"


def test_upload_rejects_non_allowlisted_domain_when_strict(tmp_path: Path) -> None:
    client, tenant_token = _bootstrap_client(tmp_path)
    with client:
        r = client.post(
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
    assert r.status_code == 400
    assert r.json().get("detail") == "base_url_not_monitored_domain"


def test_upload_accepts_allowlisted_domain_and_patch_rejects_reserved(tmp_path: Path) -> None:
    client, tenant_token = _bootstrap_client(tmp_path)
    with client:
        r = client.post(
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
        assert r.status_code == 200
        test_id = r.json()["test"]["id"]

        r2 = client.patch(
            f"/api/v1/tests/{test_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"base_url": "https://example.com"},
        )
    assert r2.status_code == 400
    assert r2.json().get("detail") == "base_url_not_allowed_host"
