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
from domain_checks.main import load_config
from e2e_registry.app import create_app
from e2e_registry.monitor_dashboard import MonitorData, build_dashboard_summary
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
                "inventory": {
                    "version": 1,
                    "reviewed_at": "2026-08-24",
                    "authoritative_sources": ["test fixture"],
                },
                "domain_groups": {
                    "core": {
                        "label": "PitchAI core",
                        "description": "Primary platform routes",
                        "order": 10,
                    },
                    "clients": {
                        "label": "Client systems",
                        "description": "Client-owned deployments",
                        "order": 20,
                    },
                },
                "domains": [
                    {
                        "domain": "a.example",
                        "label": "Primary test route",
                        "group": "core",
                        "environment": "production",
                        "kind": "application",
                        "sources": ["test fixture"],
                    },
                    {
                        "domain": "b.example",
                        "label": "Disabled client route",
                        "group": "clients",
                        "environment": "staging",
                        "kind": "application",
                        "sources": ["test fixture"],
                        "disabled": True,
                        "disabled_reason": "temporary",
                    },
                ],
                "retired_domains": [
                    {
                        "domain": "old.example",
                        "classification": "retired",
                        "reason": "test-only retired route",
                        "sources": ["test fixture"],
                    }
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
async def test_monitor_dashboard_entra_identity_and_renders(dashboard_server: dict[str, str]) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    base_url = dashboard_server["base_url"]
    token = dashboard_server["monitor_token"]

    async with httpx.AsyncClient(base_url=base_url) as client:
        assert (await client.get("/dashboard")).status_code == 401
        assert (
            await client.get(
                "/dashboard",
                headers={"X-PitchAI-Email": "operator@example.com"},
            )
        ).status_code == 401
        summary_response = await client.get(
                "/dashboard/api/v1/monitoring/summary",
                headers={"X-PitchAI-Email": "operator@pitchai.net"},
            )
        assert summary_response.status_code == 200
        summary = summary_response.json()
        assert summary["freshness"]["status"] == "fresh"
        assert summary["service_health"] == {
            "enabled": 1,
            "healthy": 1,
            "down": 0,
            "alertable_down": 0,
            "expected_down": 0,
            "unknown": 0,
            "disabled": 1,
        }
        assert [group["id"] for group in summary["domain_groups"]] == ["core", "clients"]
        assert summary["inventory"]["active_domains"] == 2
        assert summary["inventory"]["retired_domains"] == 1
        assert summary["e2e"]["total_tests"] == 0
        assert summary["incidents"] == []
        assert summary["daily_status"]["observations"] == 3
        assert summary["daily_status"]["problem_events"] == 1
        assert summary["daily_status"]["recoveries"] == 1
        assert (
            await client.get(
                "/dashboard/api/v1/monitoring/summary",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).status_code == 401
        assert (
            await client.get(
                "/api/v1/monitoring/summary",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).status_code == 200
        assert (
            await client.get(
                "/api/v1/monitoring/summary",
                headers={"X-PitchAI-Email": "operator@pitchai.net"},
            )
        ).status_code == 401
        assert (await client.get("/dashboard/login")).status_code == 404
        dashboard_html = await client.get(
            "/dashboard",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        assert "cdn.jsdelivr.net" not in dashboard_html.text
        assert "/dashboard/assets/monitoring-dashboard.js" in dashboard_html.text
        assert (await client.get("/dashboard/assets/monitoring-dashboard.css")).status_code == 200
        assert (await client.get("/dashboard/assets/monitoring-dashboard.js")).status_code == 200

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            extra_http_headers={"X-PitchAI-Email": "operator@pitchai.net"}
        )
        page = await context.new_page()
        console_errors: list[str] = []
        page_errors: list[str] = []
        failed_requests: list[str] = []
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(request.url))
        try:
            await page.goto(f"{base_url}/dashboard")
            await page.wait_for_selector("[data-testid=dash-title]")
            assert await page.locator("[data-testid=operator-identity]").inner_text() == "operator@pitchai.net"
            await page.wait_for_selector("[data-testid=dash-domains-table] tbody tr[data-domain]")
            await page.wait_for_function("document.querySelector('#kpi-services').textContent === '1/1'")
            assert await page.locator("[data-testid=dash-selected-domain]").inner_text() == "a.example"
            assert await page.locator("[data-testid=dash-domain-groups] button").count() == 3
            assert "2 monitored domains" in await page.locator("#domain-inventory-note").inner_text()
            await page.locator("#domain-group-grid button[data-group='clients']").click()
            await page.wait_for_selector("tr[data-domain='b.example']")
            assert "DISABLED" in await page.locator("tr[data-domain='b.example']").inner_text()
            await page.locator("#domain-group-grid button[data-group='core']").click()
            await page.wait_for_selector("tr[data-domain='a.example']")
            assert await page.locator("[data-testid=dash-incidents]").inner_text() == (
                "No current incidents. All latest effective checks are healthy."
            )
            await page.wait_for_selector("[data-testid=dash-chart-domain-ok] path")
            assert await page.locator("[data-testid=dash-chart-domain-ok] path").count() == 2

            # Dispatcher/agent conclusion should be visible.
            await page.wait_for_selector("[data-testid=dash-dispatch-table] .diagnostic")
            text = await page.locator("[data-testid=dash-dispatch-table]").inner_text()
            assert "Root cause" in text

            await page.set_viewport_size({"width": 390, "height": 844})
            await page.reload()
            await page.wait_for_selector("[data-testid=dash-domains-table] tbody tr[data-domain]")
            viewport = await page.evaluate(
                """() => ({
                    innerWidth: window.innerWidth,
                    documentWidth: document.documentElement.scrollWidth,
                    bodyWidth: document.body.scrollWidth,
                    overflowing: Array.from(document.querySelectorAll("body *"))
                        .map((element) => {
                            const rect = element.getBoundingClientRect();
                            return {
                                tag: element.tagName,
                                id: element.id,
                                className: String(element.className || ""),
                                left: Math.round(rect.left),
                                right: Math.round(rect.right),
                            };
                        })
                        .filter((item) => item.left < 0 || item.right > window.innerWidth + 1)
                        .slice(0, 12),
                })"""
            )
            overflow_diagnostic = json.dumps(viewport, indent=2)
            assert viewport["documentWidth"] <= viewport["innerWidth"], overflow_diagnostic
            assert viewport["bodyWidth"] <= viewport["innerWidth"], overflow_diagnostic
            assert viewport["overflowing"] == [], overflow_diagnostic
            assert console_errors == []
            assert page_errors == []
            assert failed_requests == []
        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_dashboard_renders_the_complete_production_inventory(
    dashboard_server: dict[str, str],
) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    now = time.time()
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    domain_names = [str(entry["domain"]) for entry in config["domains"]]
    state = {
        "updated_at": now,
        "last_ok": {domain: domain != "agentcloud.pitchai.net" for domain in domain_names},
        "fail_streak": {domain: 3 if domain == "agentcloud.pitchai.net" else 0 for domain in domain_names},
        "success_streak": {domain: 0 if domain == "agentcloud.pitchai.net" else 3 for domain in domain_names},
        "history": {
            domain: (
                [[now - 60, False, 100.0, 250.0, 502], [now, False, 90.0, 230.0, 502]]
                if domain == "agentcloud.pitchai.net"
                else [[now - 60, True, 100.0, 250.0, 200], [now, True, 90.0, 230.0, 200]]
            )
            for domain in domain_names
        },
    }
    summary = build_dashboard_summary(
        data=MonitorData(
            state=state,
            config=config,
            state_path="/monitor/state.json",
            config_path=str(config_path),
            loaded_at_ts=now,
            state_error=None,
        ),
        now_ts=now,
        e2e_status_summary=None,
        e2e_dispatch_runs=[],
    )
    assert summary["inventory"]["active_domains"] == 60
    assert summary["inventory"]["groups"] == 14

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            extra_http_headers={"X-PitchAI-Email": "operator@pitchai.net"}
        )
        page = await context.new_page()
        console_errors: list[str] = []
        page_errors: list[str] = []
        failed_requests: list[str] = []
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(request.url))

        async def serve_monitor_data(route) -> None:
            if "/monitoring/summary" in route.request.url:
                await route.fulfill(json=summary)
                return
            await route.fulfill(
                json={
                    "ok": True,
                    "domain": "fixture",
                    "samples": [
                        {"ts": now - 60, "ok": True, "http_ms": 100.0, "browser_ms": 250.0},
                        {"ts": now, "ok": True, "http_ms": 90.0, "browser_ms": 230.0},
                    ],
                }
            )

        await page.route("**/dashboard/api/v1/monitoring/**", serve_monitor_data)
        try:
            await page.goto(f"{dashboard_server['base_url']}/dashboard")
            await page.wait_for_function("document.querySelector('#kpi-services').textContent === '59/60'")
            assert await page.locator("[data-testid=dash-domain-groups] button").count() == 15
            assert "60 monitored domains" in await page.locator("#domain-inventory-note").inner_text()
            assert "1 expected" in await page.locator("#kpi-services-detail").inner_text()

            await page.locator("[data-testid=dash-domain-filter]").fill("AgentCloud")
            await page.wait_for_selector("tr[data-domain='agentcloud.pitchai.net']")
            agentcloud_row = await page.locator("tr[data-domain='agentcloud.pitchai.net']").inner_text()
            assert "DOWN" in agentcloud_row
            assert "EXPECTED · NO ALERTS" in agentcloud_row
            await page.locator("tr[data-domain='agentcloud.pitchai.net']").click()
            assert "Dashboard only · no Telegram alerts" in await page.locator(
                "#selected-domain-meta"
            ).inner_text()
            incident_text = await page.locator("[data-testid=dash-incidents]").inner_text()
            assert "expected / dashboard only" in incident_text.lower()
            assert "no Telegram alert is routed" in incident_text

            await page.locator("[data-testid=dash-domain-filter]").fill("Formatief Toetsen")
            await page.wait_for_function(
                "document.querySelectorAll('[data-testid=dash-domains-table] tr[data-domain]').length === 3"
            )
            rendered_dft = set(
                await page.locator("[data-testid=dash-domains-table] tr[data-domain]").evaluate_all(
                    "rows => rows.map(row => row.dataset.domain)"
                )
            )
            assert rendered_dft == {
                "formatief-toetsen.pitchai.net",
                "staging.formatief-toetsen.pitchai.net",
                "dft-marketing-staging.pitchai.net",
            }

            await page.set_viewport_size({"width": 390, "height": 844})
            viewport = await page.evaluate(
                """() => ({
                    innerWidth: window.innerWidth,
                    documentWidth: document.documentElement.scrollWidth,
                    bodyWidth: document.body.scrollWidth,
                })"""
            )
            assert viewport["documentWidth"] <= viewport["innerWidth"]
            assert viewport["bodyWidth"] <= viewport["innerWidth"]
            assert console_errors == []
            assert page_errors == []
            assert failed_requests == []
        finally:
            await context.close()
            await browser.close()
