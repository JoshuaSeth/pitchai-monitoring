CHECK = {
    "domain": "autopar.pitchai.net",
    "url": "https://autopar.pitchai.net",
    "expected_title_contains": "AutoPAR Web App",
    "required_selectors_all": [
        {"selector": "script#wss-connection", "state": "attached"},
        {"selector": "input[name=token], #token", "state": "visible"},
    ],
    "api_contract_checks": [
        {
            "name": "health",
            "method": "GET",
            "path": "/health",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["status", "timestamp", "runtime_config_version"],
            "json_paths_equal": {"status": "healthy"},
            "max_elapsed_ms": 1500,
        }
    ],
    "synthetic_transactions": [
        {
            "name": "token_login_landing",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "input[name=token], #token", "state": "visible"},
                {"type": "wait_for_selector", "selector": "script#wss-connection", "state": "attached"},
                {"type": "expect_text", "text": "AutoPAR"},
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
