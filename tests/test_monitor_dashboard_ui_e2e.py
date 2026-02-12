from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable
from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings


def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


@pytest.fixture()
def dashboard_server(tmp_path: Path) -> dict[str, str]:
    db_path = tmp_path / "e2e-registry.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tests_dir = tmp_path / "submitted-tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    monitor_state = tmp_path / "monitor_state.json"
    monitor_cfg = tmp_path / "monitor_config.yaml"

    now = time.time()
    monitor_state.write_text(
        json.dumps(
            {
                "version": 5,
                "history_ok_mode": "effective",
                "last_ok": {"a.example": True},
                "fail_streak": {"a.example": 0},
                "success_streak": {"a.example": 12},
                "history": {
                    "a.example": [
                        [now - 120, True, 120.0, 420.0, 200],
                        [now - 60, True, 140.0, 450.0, 200],
                        [now, True, 110.0, 400.0, 200],
                    ]
                },
                "signal_history": {
                    "browser": [[now - 60, 1, 0, 0], [now, 1, 0, 0]],
                    "host_health": [[now - 60, 1, 55.0, 0.0, 12.0, 0.7, 42.0, 0], [now, 1, 56.0, 0.0, 13.0, 0.8, 43.0, 0]],
                    "performance": [[now - 60, 1, 0], [now, 1, 0]],
                    "slo": [[now, 1, 0]],
                    "red": [[now, 1, 0]],
                    "tls": [[now, 1, 0]],
                    "dns": [[now, 1, 0]],
                    "container_health": [[now, 1, 0]],
                    "proxy": [[now, 1, 0]],
                    "meta": [[now, 1, 0]],
                },
                "dispatch_history": [
                    {
                        "ts": now - 30,
                        "state_key": "host_health",
                        "title": "Host health degraded",
                        "queue_state": "processed",
                        "ui_url": "https://dispatch.pitchai.net/ui/runs/example",
                        "ok": True,
                        "agent_message": "Root cause: test data. Suggested: observe only.",
                    }
                ],
                "dispatch_last": {
                    "host_health": {
                        "ts": now - 30,
                        "state_key": "host_health",
                        "queue_state": "processed",
                        "ui_url": "https://dispatch.pitchai.net/ui/runs/example",
                        "ok": True,
                        "agent_message": "Root cause: test data. Suggested: observe only.",
                    }
                },
                "events": [
                    {"ts": now - 30, "kind": "host_health_degraded", "violations": ["CPU: 95% > 80%"]},
                    {"ts": now - 10, "kind": "domain_up", "domain": "a.example"},
                ],
                "host_last_snapshot": {
                    "mem_used_percent": 56.0,
                    "swap_used_percent": 0.0,
                    "cpu_used_percent": 13.0,
                    "load1_per_cpu": 0.8,
                    "disk": {"/": {"used_percent": 43.0}},
                },
                "browser_degraded_active": False,
                "browser_degraded_first_seen_ts": 0.0,
                "browser_launch_last_error": None,
                "browser_degraded_last_notice_ts": 0.0,
                "host_health": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
                "performance": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
                "slo": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
                "red": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
                "tls": {"last_ok": True, "fail_streak": 0, "success_streak": 10, "last_run_ts": now},
                "dns": {"last_ok": True, "fail_streak": 0, "success_streak": 10, "last_run_ts": now, "last_ips": {}},
                "container_health": {"last_ok": True, "fail_streak": 0, "success_streak": 10, "last_run_ts": now, "restart_counts": {}},
                "proxy": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
                "meta": {"last_ok": True, "fail_streak": 0, "success_streak": 10, "state_write_fail_streak": 0},
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monitor_cfg.write_text(
        yaml.safe_dump(
            {
                "interval_seconds": 60,
                "history": {"retention_days": 14},
                "performance": {"http_elapsed_ms_max": 1500, "browser_elapsed_ms_max": 4000},
                "domains": [
                    {"domain": "a.example"},
                    {"domain": "b.example", "disabled": True, "disabled_reason": "temporary"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    settings = RegistrySettings(
        db_path=str(db_path),
        artifacts_dir=str(artifacts_dir),
        tests_dir=str(tests_dir),
        admin_token="adm_dash_token",
        monitor_token="mon_dash_token",
        runner_token="run_dash_token",
        alerts_enabled=False,
        dispatch_enabled=False,
        public_base_url="",
        monitor_state_path=str(monitor_state),
        monitor_config_path=str(monitor_cfg),
        dashboard_require_auth=True,
        dashboard_max_points=500,
    )
    app = create_app(settings)

    port = _pick_free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
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
        yield {"base_url": base_url, "monitor_token": settings.monitor_token}
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_monitor_dashboard_login_and_renders(dashboard_server: dict[str, str]) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    base_url = dashboard_server["base_url"]
    token = dashboard_server["monitor_token"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(f"{base_url}/dashboard")
            await page.wait_for_selector("[data-testid=dash-login-title]")
            await page.locator("[data-testid=dash-login-key]").fill(token)
            await page.locator("[data-testid=dash-login-submit]").click()

            await page.wait_for_selector("[data-testid=dash-title]")
            await page.wait_for_selector("[data-testid=dash-domains-table] tbody tr")
            assert await page.locator("[data-testid=dash-selected-domain]").inner_text() == "a.example"

            # Dispatcher/agent conclusion should be visible.
            await page.wait_for_selector("[data-testid=dash-dispatch-table] tbody tr")
            text = await page.locator("[data-testid=dash-dispatch-table]").inner_text()
            assert "Root cause" in text
        finally:
            await context.close()
            await browser.close()

