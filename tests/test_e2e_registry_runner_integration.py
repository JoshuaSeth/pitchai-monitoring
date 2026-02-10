from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn

from domain_checks.common_check import find_chromium_executable
from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings


def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


class _SiteHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        routes: dict[str, tuple[int, dict[str, str], str]] = {
            "/": (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                (
                    "<!doctype html><html><head><title>Home</title></head>"
                    "<body><a href='/ok' id='oklink'>OK</a></body></html>"
                ),
            ),
            "/ok": (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                (
                    "<!doctype html><html><head><title>OK Page</title></head>"
                    "<body><nav>nav</nav><h1>Everything is fine</h1>"
                    "<div id='items'><span class='item'>a</span><span class='item'>b</span></div>"
                    "</body></html>"
                ),
            ),
        }

        status, headers, body = routes.get(
            self.path,
            (404, {"Content-Type": "text/plain; charset=utf-8"}, "Not Found"),
        )
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


@pytest.fixture(scope="module")
def local_site_base_url() -> str:
    httpd = HTTPServer(("127.0.0.1", 0), _SiteHandler)
    host, port = httpd.server_address
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


@pytest.fixture()
def registry_server(tmp_path: Path):
    """
    Starts e2e-registry as a real HTTP server (uvicorn) on localhost.
    """
    db_path = tmp_path / "e2e-registry.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tests_dir = tmp_path / "submitted-tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    settings = RegistrySettings(
        db_path=str(db_path),
        artifacts_dir=str(artifacts_dir),
        tests_dir=str(tests_dir),
        admin_token="adm_test_token",
        monitor_token="mon_test_token",
        runner_token="run_test_token",
        alerts_enabled=False,  # tests should never emit real Telegram
        dispatch_enabled=False,
        public_base_url="",
    )
    app = create_app(settings)

    port = _pick_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    with httpx.Client() as client:
        for _ in range(80):
            try:
                r = client.get(f"{base_url}/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("registry server did not start")

    try:
        yield {"base_url": base_url, "settings": settings}
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_e2e_registry_and_runner_end_to_end(
    registry_server: dict[str, object],
    local_site_base_url: str,
    tmp_path: Path,
) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    base_url = str(registry_server["base_url"])
    settings: RegistrySettings = registry_server["settings"]  # type: ignore[assignment]

    async with httpx.AsyncClient() as client:
        # Create tenant + API key (admin).
        r = await client.post(
            f"{base_url}/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {settings.admin_token}"},
            json={"name": "external-dev-tenant"},
            timeout=5.0,
        )
        r.raise_for_status()
        tenant_id = r.json()["tenant"]["id"]

        r = await client.post(
            f"{base_url}/api/v1/admin/api_keys",
            headers={"Authorization": f"Bearer {settings.admin_token}"},
            json={"tenant_id": tenant_id, "name": "dev-key"},
            timeout=5.0,
        )
        r.raise_for_status()
        tenant_token = r.json()["token"]

        # Create a passing Playwright-Python test and a failing Puppeteer-JS test (tenant) via file upload.
        py_src = "\n".join(
            [
                "async def run(page, base_url, artifacts_dir):",
                "    url = base_url.rstrip('/') + '/ok'",
                "    await page.goto(url, wait_until='domcontentloaded')",
                "    body = await page.evaluate(\"() => document.body?.innerText || ''\")",
                "    assert 'Everything is fine' in (body or '')",
                "",
            ]
        )
        js_src_fail = "\n".join(
            [
                "module.exports.run = async ({ page, baseUrl, artifactsDir }) => {",
                "  const url = String(baseUrl || '').replace(/\\/$/, '') + '/ok';",
                "  await page.goto(url, { waitUntil: 'domcontentloaded' });",
                "  const body = await page.evaluate(() => document.body?.innerText || '');",
                "  if (!String(body || '').includes('THIS SHOULD NOT EXIST')) {",
                "    throw new Error('text_missing: THIS SHOULD NOT EXIST');",
                "  }",
                "};",
                "",
            ]
        )

        r = await client.post(
            f"{base_url}/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": "pass_local_py",
                "base_url": local_site_base_url,
                "kind": "playwright_python",
                "interval_seconds": "3600",
                "timeout_seconds": "15",
                "jitter_seconds": "0",
                "down_after_failures": "1",
                "up_after_successes": "1",
                "notify_on_recovery": "0",
                "dispatch_on_failure": "0",
            },
            files={"file": ("pass_test.py", py_src.encode("utf-8"), "text/x-python")},
            timeout=20.0,
        )
        r.raise_for_status()
        pass_test_id = r.json()["test"]["id"]

        r = await client.post(
            f"{base_url}/api/v1/tests/upload",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "name": "fail_local_js",
                "base_url": local_site_base_url,
                "kind": "puppeteer_js",
                "interval_seconds": "3600",
                "timeout_seconds": "15",
                "jitter_seconds": "0",
                "down_after_failures": "1",
                "up_after_successes": "1",
                "notify_on_recovery": "0",
                "dispatch_on_failure": "0",
            },
            files={"file": ("fail_test.js", js_src_fail.encode("utf-8"), "application/javascript")},
            timeout=20.0,
        )
        r.raise_for_status()
        fail_test_id = r.json()["test"]["id"]

    # Run the real runner once (subprocess) against the real registry server.
    env = os.environ.copy()
    env.update(
        {
            "CHROMIUM_PATH": chromium_path,
            "E2E_REGISTRY_BASE_URL": base_url,
            "E2E_REGISTRY_RUNNER_TOKEN": settings.runner_token,
            # Runner and registry must share the same artifacts dir for downloads to work.
            "E2E_ARTIFACTS_DIR": str(settings.artifacts_dir),
            "E2E_TESTS_DIR": str(settings.tests_dir),
            "E2E_RUNNER_CONCURRENCY": "5",
            "E2E_RUNNER_TRACE_ON_FAILURE": "0",
        }
    )
    Path(env["E2E_ARTIFACTS_DIR"]).mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [sys.executable, "-m", "e2e_runner.main", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"runner failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    async with httpx.AsyncClient() as client:
        # Verify status summary works (monitor token).
        r = await client.get(
            f"{base_url}/api/v1/status/summary",
            headers={"Authorization": f"Bearer {settings.monitor_token}"},
            timeout=10.0,
        )
        r.raise_for_status()
        summary = r.json()
        assert summary["ok"] is True
        assert summary["total_tests"] >= 2
        assert summary["failing_tests"] >= 1

        # Verify pass test has a PASS run.
        r = await client.get(
            f"{base_url}/api/v1/tests/{pass_test_id}/runs",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()
        pass_runs = r.json()["runs"]
        assert pass_runs, "expected at least one pass run"
        assert pass_runs[0]["status"] == "pass"

        # Verify fail test has a FAIL run and artifacts exist.
        r = await client.get(
            f"{base_url}/api/v1/tests/{fail_test_id}/runs",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()
        fail_runs = r.json()["runs"]
        assert fail_runs, "expected at least one failing run"
        assert fail_runs[0]["status"] in {"fail", "infra_degraded"}

        # Fetch the run and assert failure artifacts were captured and downloadable.
        failing_run_id = fail_runs[0]["id"]
        r = await client.get(
            f"{base_url}/api/v1/runs/{failing_run_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()
        run = r.json()["run"]
        artifacts = json.loads(run.get("artifacts_json") or "{}")
        # For real failures we expect these (infra_degraded may have none).
        if run.get("status") == "fail":
            assert artifacts.get("failure_screenshot") == "failure.png"
            assert artifacts.get("run_log") == "run.log"
            art = await client.get(
                f"{base_url}/api/v1/runs/{failing_run_id}/artifacts/failure.png",
                headers={"Authorization": f"Bearer {tenant_token}"},
                timeout=20.0,
            )
            assert art.status_code == 200

        # Disable the failing test temporarily and ensure it is not claimed even if run-now is triggered.
        until_ts = time.time() + 3600
        r = await client.post(
            f"{base_url}/api/v1/tests/{fail_test_id}/disable",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"reason": "temporary disable", "until": until_ts},
            timeout=10.0,
        )
        r.raise_for_status()

        r = await client.post(
            f"{base_url}/api/v1/tests/{fail_test_id}/run",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()

    proc2 = subprocess.run(
        [sys.executable, "-m", "e2e_runner.main", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc2.returncode == 0

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{base_url}/api/v1/tests/{fail_test_id}/runs",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()
        fail_runs2 = r.json()["runs"]
        assert len(fail_runs2) == len(fail_runs), "disabled test should not have produced new runs"

        # Recovery path: update failing test to pass, enable, run-now, execute runner, and verify effective_ok flips to OK.
        r = await client.post(
            f"{base_url}/api/v1/tests/{fail_test_id}/enable",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()

        js_src_pass = "\n".join(
            [
                "module.exports.run = async ({ page, baseUrl, artifactsDir }) => {",
                "  const url = String(baseUrl || '').replace(/\\/$/, '') + '/ok';",
                "  await page.goto(url, { waitUntil: 'domcontentloaded' });",
                "  const body = await page.evaluate(() => document.body?.innerText || '');",
                "  if (!String(body || '').includes('Everything is fine')) {",
                "    throw new Error('text_missing: Everything is fine');",
                "  }",
                "};",
                "",
            ]
        )
        r = await client.post(
            f"{base_url}/api/v1/tests/{fail_test_id}/source",
            headers={"Authorization": f"Bearer {tenant_token}"},
            files={"file": ("pass_test.js", js_src_pass.encode("utf-8"), "application/javascript")},
            timeout=20.0,
        )
        r.raise_for_status()

        r = await client.post(
            f"{base_url}/api/v1/tests/{fail_test_id}/run",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()

    proc3 = subprocess.run(
        [sys.executable, "-m", "e2e_runner.main", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc3.returncode == 0

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{base_url}/api/v1/tests/{fail_test_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=10.0,
        )
        r.raise_for_status()
        test = r.json()["test"]
        assert int(test.get("effective_ok") or 0) == 1
