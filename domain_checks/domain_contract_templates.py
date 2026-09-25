# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared strict contracts for related monitored applications."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain_checks.types import JsonObject

STANDARD_FAILURE_TEXT = [
    "maintenance",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
]


def build_afasask_api_checks(health_name: str) -> list[JsonObject]:
    """Build the shared AFAS Ask health and no-quota readiness checks.

    Returns:
        Independent API check mappings for one AFAS Ask deployment.
    """
    return [
        {
            "name": health_name,
            "path": "/health",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_equal": {"status": "ok"},
            "max_elapsed_ms": 1500,
        },
        {
            "name": "codex_no_quota_readiness",
            "path": "/internal/monitor/codex-readiness",
            "headers": {"Authorization": "Bearer ${AFASASK_MONITOR_TOKEN}"},
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_equal": {
                "status": "ok",
                "quota_used": False,
                "prompt_submitted": False,
                "generation_started": False,
                "afasask.temp_codex_home_materialized": True,
                "broker_canary.status": "ok",
                "broker_canary.response.status": "ok",
            },
            "json_paths_required": [
                "checked_at",
                "afasask.account_id_hash",
                "broker_canary.response.selected_account.account_id_hash",
                "broker_canary.response.pool.selectable_accounts",
            ],
            "max_elapsed_ms": 20000,
        },
    ]


def build_planbook_check(
    *,
    domain: str,
    url: str,
    expected_final_host_suffix: str | None = None,
) -> JsonObject:
    """Build the shared Deplanbook application contract.

    Returns:
        A domain-specific Deplanbook check mapping.
    """
    check: JsonObject = {
        "domain": domain,
        "url": url,
        "expected_title_contains": "Deplanbook",
        "required_selectors_all": [
            {"selector": "#main", "state": "visible"},
            {"selector": 'a[href="/diary"]', "state": "visible"},
            {"selector": 'a[href="/account"]', "state": "visible"},
            {"selector": "text=Rondleiding", "state": "visible"},
        ],
        "required_selectors_any": [
            {"selector": 'a[href="/diary"]', "state": "attached"},
        ],
        "api_contract_checks": [
            {
                "name": "health",
                "method": "GET",
                "path": "/health",
                "expected_status_codes": [200],
                "expected_content_type_contains": "application/json",
                "json_paths_required": ["status"],
                "json_paths_equal": {"status": "ok"},
                "max_elapsed_ms": 1500,
            },
        ],
        "synthetic_transactions": [
            {
                "name": "open_diary_page",
                "steps": [
                    {"type": "goto"},
                    {"type": "click", "selector": 'a[href="/diary"]'},
                    {"type": "expect_url_contains", "value": "/diary"},
                ],
            },
        ],
        "forbidden_text_any": [*STANDARD_FAILURE_TEXT, "not found"],
    }
    if expected_final_host_suffix is not None:
        check["expected_final_host_suffix"] = expected_final_host_suffix
    return check
