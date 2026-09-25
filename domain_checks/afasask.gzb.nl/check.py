# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for check."""

from domain_checks.domain_contract_templates import (
    STANDARD_FAILURE_TEXT,
    build_afasask_api_checks,
)

CHECK = {
    "domain": "afasask.gzb.nl",
    "url": "https://afasask.gzb.nl/chat_mini/gzb/start?floating=false&reload=true&mode=codex&intensity=medium",
    "http_timeout_seconds": 30.0,
    "browser_timeout_seconds": 60.0,
    "allowed_status_codes": [200],
    "expected_title_contains": "GZB - Chat",
    "required_selectors_all": [
        {"selector": "#chat-input", "state": "visible"},
        {"selector": ".chat-submit", "state": "visible"},
        {"selector": "text=/AFASASK/i", "state": "visible"},
        {"selector": "text=/Medium/i", "state": "visible"},
    ],
    "api_contract_checks": build_afasask_api_checks("afasask_health"),
    "synthetic_transactions": [
        {
            "name": "codex_medium_shell_ready",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "#chat-input", "state": "visible"},
                {"type": "wait_for_selector", "selector": ".chat-submit", "state": "visible"},
                {
                    "type": "wait_for_selector",
                    "selector": "[data-testid='codex-intensity-selector']",
                    "state": "visible",
                },
            ],
        },
    ],
    "forbidden_text_any": list(STANDARD_FAILURE_TEXT),
}
