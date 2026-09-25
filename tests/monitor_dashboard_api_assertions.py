# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP contract checks for the authenticated monitoring dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from e2e_registry.models import parse_json_object, require_json_object

if TYPE_CHECKING:
    from e2e_registry.models import JsonObject
    from tests.monitor_dashboard_server_support import DashboardServer

_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404
_EXPECTED_ACTIVE_DOMAINS = 2
_EXPECTED_OBSERVATIONS = 3


def _verify_summary_payload(summary: JsonObject) -> None:
    freshness = require_json_object(
        summary.get("freshness"), label="dashboard freshness",
    )
    health = require_json_object(
        summary.get("service_health"), label="dashboard service health",
    )
    inventory = require_json_object(
        summary.get("inventory"), label="dashboard inventory",
    )
    daily = require_json_object(
        summary.get("daily_status"), label="dashboard daily status",
    )
    e2e = require_json_object(summary.get("e2e"), label="dashboard E2E status")
    expected_health = {
        "enabled": 1,
        "healthy": 1,
        "down": 0,
        "alertable_down": 0,
        "expected_down": 0,
        "unknown": 0,
        "disabled": 1,
    }
    if freshness.get("status") != "fresh":
        message = "dashboard summary freshness must be fresh"
        raise AssertionError(message)
    if health != expected_health:
        message = f"unexpected dashboard service health: {health!r}"
        raise AssertionError(message)
    groups = summary.get("domain_groups")
    if not isinstance(groups, list):
        message = "dashboard domain groups must be a list"
        raise TypeError(message)
    group_ids = [
        require_json_object(group, label="dashboard group").get("id")
        for group in groups
    ]
    if group_ids != ["core", "clients"]:
        message = f"unexpected dashboard group order: {group_ids!r}"
        raise AssertionError(message)
    if inventory.get("active_domains") != _EXPECTED_ACTIVE_DOMAINS:
        message = "dashboard must report two active fixture domains"
        raise AssertionError(message)
    if inventory.get("retired_domains") != 1:
        message = "dashboard must report one retired fixture domain"
        raise AssertionError(message)
    if e2e.get("total_tests") != 0:
        message = "dashboard fixture must not report E2E tests"
        raise AssertionError(message)
    if summary.get("incidents") != []:
        message = "dashboard fixture must not report incidents"
        raise AssertionError(message)
    if daily.get("observations") != _EXPECTED_OBSERVATIONS:
        message = "dashboard fixture must report three observations"
        raise AssertionError(message)
    if daily.get("problem_events") != 1:
        message = "dashboard fixture must report one problem event"
        raise AssertionError(message)
    if daily.get("recoveries") != 1:
        message = "dashboard fixture must report one recovery"
        raise AssertionError(message)


async def _verify_dashboard_authentication(
    client: httpx.AsyncClient,
    server: DashboardServer,
) -> None:
    anonymous = await client.get("/dashboard")
    if anonymous.status_code != _HTTP_UNAUTHORIZED:
        message = "anonymous dashboard access must be unauthorized"
        raise AssertionError(message)
    external = await client.get(
        "/dashboard",
        headers={"X-PitchAI-Email": "operator@example.com"},
    )
    if external.status_code != _HTTP_UNAUTHORIZED:
        message = "non-PitchAI dashboard identity must be unauthorized"
        raise AssertionError(message)
    dashboard_token = await client.get(
        "/dashboard/api/v1/monitoring/summary",
        headers={"Authorization": f"Bearer {server.monitor_token}"},
    )
    if dashboard_token.status_code != _HTTP_UNAUTHORIZED:
        message = "monitor token must not authenticate dashboard API routes"
        raise AssertionError(message)
    monitor_api = await client.get(
        "/api/v1/monitoring/summary",
        headers={"Authorization": f"Bearer {server.monitor_token}"},
    )
    if monitor_api.status_code != _HTTP_OK:
        message = "monitor token must authenticate the monitor API"
        raise AssertionError(message)
    monitor_identity = await client.get(
        "/api/v1/monitoring/summary",
        headers={"X-PitchAI-Email": "operator@pitchai.net"},
    )
    if monitor_identity.status_code != _HTTP_UNAUTHORIZED:
        message = "dashboard identity must not authenticate monitor API routes"
        raise AssertionError(message)
    login = await client.get("/dashboard/login")
    if login.status_code != _HTTP_NOT_FOUND:
        message = "dashboard must not expose a local login route"
        raise AssertionError(message)


async def _verify_dashboard_assets(client: httpx.AsyncClient) -> None:
    html = await client.get(
        "/dashboard",
        headers={"X-PitchAI-Email": "operator@pitchai.net"},
    )
    if "cdn.jsdelivr.net" in html.text:
        message = "dashboard HTML must not depend on jsDelivr"
        raise AssertionError(message)
    if "/dashboard/assets/monitoring-dashboard.js" not in html.text:
        message = "dashboard HTML must load the local JavaScript asset"
        raise AssertionError(message)
    css = await client.get("/dashboard/assets/monitoring-dashboard.css")
    if css.status_code != _HTTP_OK:
        message = "dashboard stylesheet must be served"
        raise AssertionError(message)
    javascript = await client.get("/dashboard/assets/monitoring-dashboard.js")
    if javascript.status_code != _HTTP_OK:
        message = "dashboard JavaScript must be served"
        raise AssertionError(message)


async def verify_dashboard_api(server: DashboardServer) -> None:
    """Verify the dashboard's identity, API, and local-asset contracts.

    Raises:
        AssertionError: If the dashboard violates an access or response contract.
    """
    async with httpx.AsyncClient(base_url=server.base_url) as client:
        await _verify_dashboard_authentication(client, server)
        response = await client.get(
            "/dashboard/api/v1/monitoring/summary",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        if response.status_code != _HTTP_OK:
            message = "PitchAI dashboard identity must access dashboard summary"
            raise AssertionError(message)
        summary = parse_json_object(response.content, label="dashboard summary")
        _verify_summary_payload(summary)
        await _verify_dashboard_assets(client)
