from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import httpx
import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable


pytestmark = pytest.mark.live


if os.getenv("RUN_LIVE_E2E_REGISTRY_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_E2E_REGISTRY_TESTS=1 to run live e2e-registry acceptance tests",
        allow_module_level=True,
    )


def _base_url() -> str:
    # On the prod host, the registry is exposed on 127.0.0.1:8111.
    return (
        os.getenv("E2E_REGISTRY_PUBLIC_BASE_URL")
        or os.getenv("E2E_REGISTRY_BASE_URL")
        or "http://127.0.0.1:8111"
    ).strip()


def _admin_token() -> str:
    tok = (os.getenv("E2E_REGISTRY_ADMIN_TOKEN") or "").strip()
    if not tok:
        raise RuntimeError(
            "Missing E2E_REGISTRY_ADMIN_TOKEN (export it or pass the env-file used by e2e-registry)"
        )
    return tok


async def _poll_for_completed_run(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    tenant_token: str,
    test_id: str,
    timeout_seconds: float = 240.0,
) -> dict:
    """
    The registry creates a placeholder run at claim time with:
    - status='infra_degraded'
    - error_kind='pending'
    - finished_at_ts=NULL
    We poll until the most recent run is completed.
    """
    deadline = time.time() + float(timeout_seconds)
    last = None
    while time.time() < deadline:
        r = await client.get(
            f"{base_url.rstrip('/')}/api/v1/tests/{test_id}/runs",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=15.0,
        )
        r.raise_for_status()
        runs = r.json().get("runs") or []
        if isinstance(runs, list) and runs:
            run = runs[0]
            last = run
            finished = run.get("finished_at_ts")
            error_kind = str(run.get("error_kind") or "").strip().lower()
            if finished is not None and error_kind != "pending":
                return run
        await asyncio.sleep(2.0)
    raise AssertionError(f"Timed out waiting for run completion test_id={test_id} last={last!r}")


@pytest.mark.asyncio
async def test_live_e2e_registry_api_pass_fail_artifacts_and_isolation() -> None:
    base_url = _base_url()
    admin = _admin_token()

    tenant_name = f"live-smoke-{uuid.uuid4().hex[:10]}"
    nonce = uuid.uuid4().hex[:8]

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Live E2E Registry Test"}) as client:
        # Create tenant + API key (real DB; no mocks).
        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {admin}"},
            json={"name": tenant_name},
            timeout=15.0,
        )
        r.raise_for_status()
        tenant_id = r.json()["tenant"]["id"]

        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/admin/api_keys",
            headers={"Authorization": f"Bearer {admin}"},
            json={"tenant_id": tenant_id, "name": "live-smoke-key"},
            timeout=15.0,
        )
        r.raise_for_status()
        tenant_token = r.json()["token"]

        # Passing test: Playwright-Python against a real domain + real selector.
        pass_py = "\n".join(
            [
                "async def run(page, base_url, artifacts_dir):",
                "    await page.goto(base_url.rstrip('/') + '/', wait_until='domcontentloaded')",
                "    title = await page.title()",
                "    assert 'Deplanbook' in (title or '')",
                "    await page.wait_for_selector('a[href=\"/diary\"]', state='visible', timeout=30000)",
                "",
            ]
        )

        # Failing test: Puppeteer-JS against a stable domain + guaranteed-fail assertion.
        fail_js = "\n".join(
            [
                "module.exports.run = async ({ page, baseUrl, artifactsDir }) => {",
                "  await page.goto(String(baseUrl || '').replace(/\\/$/, '') + '/', { waitUntil: 'domcontentloaded' });",
                "  const body = await page.evaluate(() => document.body?.innerText || '');",
                "  if (!String(body || '').includes('THIS SHOULD NOT EXIST')) {",
                "    throw new Error('text_missing: THIS SHOULD NOT EXIST');",
                "  }",
                "};",
                "",
            ]
        )

        # Avoid Telegram spam: do not transition effective_ok to DOWN during this smoke run.
        common_cfg = {
            "interval_seconds": 3600,
            "timeout_seconds": 35,
            "jitter_seconds": 0,
            # Keep debouncing within API limits (<=20) but high enough to avoid alerts for 1-off failures.
            "down_after_failures": 20,
            "up_after_successes": 20,
            "notify_on_recovery": False,
            "dispatch_on_failure": False,
        }

        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": f"live_pass_{nonce}",
                "base_url": "https://deplanbook.com",
                "kind": "playwright_python",
                **{k: str(v) for k, v in common_cfg.items()},
            },
            files={"file": ("live_pass.py", pass_py.encode("utf-8"), "text/x-python")},
            timeout=60.0,
        )
        r.raise_for_status()
        pass_test_id = r.json()["test"]["id"]

        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": f"live_fail_{nonce}",
                "base_url": "https://example.com",
                "kind": "puppeteer_js",
                **{k: str(v) for k, v in common_cfg.items()},
            },
            files={"file": ("live_fail.js", fail_js.encode("utf-8"), "application/javascript")},
            timeout=60.0,
        )
        r.raise_for_status()
        fail_test_id = r.json()["test"]["id"]

        # Trigger immediate runs (runner is an external service).
        for tid in (pass_test_id, fail_test_id):
            rr = await client.post(
                f"{base_url.rstrip('/')}/api/v1/tests/{tid}/run",
                headers={"Authorization": f"Bearer {tenant_token}"},
                timeout=15.0,
            )
            rr.raise_for_status()

        pass_run = await _poll_for_completed_run(
            client,
            base_url=base_url,
            tenant_token=tenant_token,
            test_id=pass_test_id,
            timeout_seconds=300.0,
        )
        assert pass_run.get("status") == "pass"
        assert pass_run.get("elapsed_ms") is not None

        fail_run = await _poll_for_completed_run(
            client,
            base_url=base_url,
            tenant_token=tenant_token,
            test_id=fail_test_id,
            timeout_seconds=300.0,
        )
        assert fail_run.get("status") == "fail"
        fail_run_id = str(fail_run.get("id") or "").strip()
        assert fail_run_id

        # Verify failure artifacts are captured and downloadable.
        rr = await client.get(
            f"{base_url.rstrip('/')}/api/v1/runs/{fail_run_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=20.0,
        )
        rr.raise_for_status()
        run = rr.json()["run"]
        artifacts = json.loads(run.get("artifacts_json") or "{}")
        assert artifacts.get("failure_screenshot") == "failure.png"
        assert artifacts.get("run_log") == "run.log"

        art = await client.get(
            f"{base_url.rstrip('/')}/api/v1/runs/{fail_run_id}/artifacts/failure.png",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=30.0,
        )
        assert art.status_code == 200
        assert art.content[:8] == b"\x89PNG\r\n\x1a\n"

        # Disabled test should not produce new runs (even if run-now is triggered).
        runs_before = await client.get(
            f"{base_url.rstrip('/')}/api/v1/tests/{fail_test_id}/runs",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=15.0,
        )
        runs_before.raise_for_status()
        before_count = len(runs_before.json().get("runs") or [])

        until_ts = time.time() + 3600
        rr = await client.post(
            f"{base_url.rstrip('/')}/api/v1/tests/{fail_test_id}/disable",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"reason": "live smoke disable", "until": until_ts},
            timeout=15.0,
        )
        rr.raise_for_status()

        rr = await client.post(
            f"{base_url.rstrip('/')}/api/v1/tests/{fail_test_id}/run",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=15.0,
        )
        rr.raise_for_status()

        await asyncio.sleep(10.0)
        runs_after = await client.get(
            f"{base_url.rstrip('/')}/api/v1/tests/{fail_test_id}/runs",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=15.0,
        )
        runs_after.raise_for_status()
        after_count = len(runs_after.json().get("runs") or [])
        assert after_count == before_count

        # Tenant isolation: another tenant can't read this test.
        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {admin}"},
            json={"name": f"live-iso-{uuid.uuid4().hex[:10]}"},
            timeout=15.0,
        )
        r.raise_for_status()
        tenant2_id = r.json()["tenant"]["id"]
        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/admin/api_keys",
            headers={"Authorization": f"Bearer {admin}"},
            json={"tenant_id": tenant2_id, "name": "iso-key"},
            timeout=15.0,
        )
        r.raise_for_status()
        tenant2_token = r.json()["token"]

        r = await client.get(
            f"{base_url.rstrip('/')}/api/v1/tests/{pass_test_id}",
            headers={"Authorization": f"Bearer {tenant2_token}"},
            timeout=15.0,
        )
        assert r.status_code == 404

        # Summary endpoint should show our newly registered tests.
        r = await client.get(
            f"{base_url.rstrip('/')}/api/v1/status/summary",
            headers={"Authorization": f"Bearer {admin}"},
            timeout=15.0,
        )
        r.raise_for_status()
        summary = r.json()
        assert summary.get("ok") is True
        tests = summary.get("tests") if isinstance(summary.get("tests"), list) else []
        names = {str(t.get("test_name") or "") for t in tests if isinstance(t, dict)}
        assert f"live_pass_{nonce}" in names
        assert f"live_fail_{nonce}" in names


@pytest.mark.asyncio
async def test_live_e2e_registry_ui_login_and_upload(tmp_path: Path) -> None:
    base_url = _base_url()
    admin = _admin_token()

    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Live E2E Registry UI Test"}) as client:
        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {admin}"},
            json={"name": f"live-ui-{uuid.uuid4().hex[:10]}"},
            timeout=15.0,
        )
        r.raise_for_status()
        tenant_id = r.json()["tenant"]["id"]
        r = await client.post(
            f"{base_url.rstrip('/')}/api/v1/admin/api_keys",
            headers={"Authorization": f"Bearer {admin}"},
            json={"tenant_id": tenant_id, "name": "ui-key"},
            timeout=15.0,
        )
        r.raise_for_status()
        tenant_token = r.json()["token"]

    test_path = tmp_path / "live_ui_test.py"
    test_path.write_text(
        "\n".join(
            [
                "async def run(page, base_url, artifacts_dir):",
                "    await page.goto(base_url.rstrip('/') + '/', wait_until='domcontentloaded')",
                "    title = await page.title()",
                "    assert 'Deplanbook' in (title or '')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context()
        page = await context.new_page()
        try:
            # Negative path: invalid key should show an error.
            await page.goto(f"{base_url.rstrip('/')}/ui/login")
            await page.locator("[data-testid=login-api-key]").fill("invalid-key")
            await page.locator("[data-testid=login-submit]").click()
            await page.wait_for_selector("[data-testid=login-error]")

            # Happy path: login succeeds and shows Tests.
            await page.locator("[data-testid=login-api-key]").fill(tenant_token)
            await page.locator("[data-testid=login-submit]").click()
            await page.wait_for_selector("[data-testid=tests-title]")

            # Upload a Playwright-Python test file.
            await page.locator("[data-testid=nav-upload]").click()
            await page.wait_for_selector("[data-testid=upload-title]")
            name = f"live_ui_created_{uuid.uuid4().hex[:6]}"
            await page.locator("[data-testid=upload-name]").fill(name)
            await page.locator("[data-testid=upload-base-url]").fill("https://deplanbook.com")
            await page.locator("[data-testid=upload-interval]").fill("3600")
            await page.locator("[data-testid=upload-kind]").select_option("playwright_python")
            await page.set_input_files("[data-testid=upload-file]", str(test_path))
            await page.locator("[data-testid=upload-submit]").click()
            await page.wait_for_selector("[data-testid=upload-msg]")

            # Verify the new test appears in the list.
            await page.locator("[data-testid=nav-tests]").click()
            await page.wait_for_selector("[data-testid=tests-table]")
            assert await page.locator("a[data-testid=test-link]", has_text=name).count() >= 1
        finally:
            await context.close()
            await browser.close()
