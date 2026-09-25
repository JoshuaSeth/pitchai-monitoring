# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for check."""

from domain_checks.domain_contract_templates import (
    STANDARD_FAILURE_TEXT,
    build_afasask_api_checks,
)

CHECK = {
    "domain": "demo.afasask.pitchai.net",
    "url": "https://demo.afasask.pitchai.net/chat/demo/start?floating=false&reload=true&mode=codex&intensity=fast",
    "http_timeout_seconds": 30.0,
    "browser_timeout_seconds": 60.0,
    "allowed_status_codes": [200],
    "expected_title_contains": "PitchAI Chat",
    "required_selectors_all": [
        {"selector": "#main", "state": "visible"},
        {"selector": "text=/Welkom bij PitchAI Chat/i", "state": "visible"},
        {"selector": "text=/Login with AFAS/i", "state": "visible"},
    ],
    "api_contract_checks": build_afasask_api_checks("afasask_demo_health"),
    "synthetic_transactions": [
        {
            "name": "authenticated_demo_entry_ready",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "#main", "state": "visible"},
                {"type": "expect_text", "text": "Welkom bij PitchAI Chat"},
                {"type": "expect_text", "text": "Login with AFAS"},
            ],
        },
    ],
    "forbidden_text_any": list(STANDARD_FAILURE_TEXT),
}
