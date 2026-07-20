CHECK = {
    "domain": "demo.afasask.pitchai.net",
    "url": "https://demo.afasask.pitchai.net/chat/demo/start?floating=false&reload=true&mode=codex&intensity=fast",
    "http_timeout_seconds": 30.0,
    "browser_timeout_seconds": 60.0,
    "allowed_status_codes": [200],
    "expected_title_contains": "PitchAI Chat",
    "required_selectors_all": [
        {"selector": "text=/Welkom bij PitchAI Chat/i", "state": "visible"},
        {"selector": "text=/Username \\/ Password/i", "state": "visible"},
        {"selector": "a[href^='/login-admin?next=']", "state": "visible"},
    ],
    "api_contract_checks": [
        {
            "name": "afasask_demo_health",
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
                "afasask.broker_concurrent_sessions_nonblocking": True,
                "afasask.broker_concurrent_session_count": 2,
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
    ],
    "synthetic_transactions": [
        {
            "name": "demo_password_gate_ready",
            "steps": [
                {"type": "goto"},
                {"type": "expect_url_contains", "value": "/login-page"},
                {"type": "expect_text", "text": "Welkom bij PitchAI Chat"},
                {"type": "wait_for_selector", "selector": "a[href^='/login-admin?next=']", "state": "visible"},
                {"type": "expect_selector_count", "selector": "#chat-input", "count": 0},
            ],
        }
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ],
}
