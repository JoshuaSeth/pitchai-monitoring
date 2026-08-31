# Copyright (c) 2026 PitchAI. All rights reserved.
"""Production monitoring configuration for the protected AFASAsk GZB chat."""

from __future__ import annotations

_JSON_200_CONTRACT: dict[str, object] = {
    "expected_status_codes": [200],
    "expected_content_type_contains": "application/json",
}
_READINESS_PATHS = (
    "status",
    "quota_used",
    "prompt_submitted",
    "generation_started",
    "afasask.temp_codex_home_materialized",
    "afasask.broker_concurrent_sessions_nonblocking",
    "afasask.broker_concurrent_session_count",
    "broker_canary.status",
    "broker_canary.response.status",
)
_READINESS_VALUES: tuple[object, ...] = (
    "ok",
    False,
    False,
    False,
    True,
    True,
    2,
    "ok",
    "ok",
)
_READINESS_REQUIRED = (
    "checked_at",
    "afasask.account_id_hash",
    "broker_canary.response.selected_account.account_id_hash",
    "broker_canary.response.pool.selectable_accounts",
)

CHECK: dict[str, object] = {
    "domain": "afasask.gzb.nl",
    "url": "https://afasask.gzb.nl/chat_mini/gzb/start?floating=false&reload=true&mode=codex&intensity=medium",
    "http_timeout_seconds": 30.0,
    "browser_timeout_seconds": 60.0,
    "allowed_status_codes": [200],
    "expected_title_contains": "PitchAI Chat",
    "expected_final_host_suffix": "afasask.gzb.nl",
    "expected_final_path": "/login-page",
    "required_selectors_all": [
        {"selector": "text=/Welkom bij PitchAI Chat/i", "state": "visible"},
        {"selector": "text=Username / Password", "state": "visible"},
        {"selector": "a[href^='/login-admin?next=']", "state": "visible"},
    ],
    "api_contract_checks": [
        _JSON_200_CONTRACT
        | {
            "name": "afasask_health",
            "path": "/health",
            "json_paths_equal": {"status": "ok"},
            "max_elapsed_ms": 1500,
        },
        _JSON_200_CONTRACT
        | {
            "name": "codex_no_quota_readiness",
            "coordination_key": "afasask_auth_broker_readiness",
            "path": "/internal/monitor/codex-readiness",
            "headers": {"Authorization": "Bearer ${AFASASK_MONITOR_TOKEN}"},
            "json_paths_equal": dict(zip(_READINESS_PATHS, _READINESS_VALUES, strict=True)),
            "json_paths_required": list(_READINESS_REQUIRED),
            "max_elapsed_ms": 20000,
        },
    ],
    "synthetic_transactions": [
        {
            "name": "gzb_authentication_boundary_ready",
            "steps": [
                {"type": "goto"},
                {"type": "expect_url_contains", "value": "/login-page"},
                {"type": "expect_title_contains", "text": "PitchAI Chat"},
                {"type": "expect_selector_count", "selector": "#chat-input", "count": 0},
            ],
        },
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ],
}
