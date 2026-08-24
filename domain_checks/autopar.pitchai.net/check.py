CHECK = {
    "domain": "autopar.pitchai.net",
    "url": "https://autopar.pitchai.net",
    "allowed_status_codes": [200],
    "expected_title_contains": "AutoPAR",
    "expected_final_host_suffix": "autopar.pitchai.net",
    "expected_final_path": "/login-page",
    "required_selectors_all": [
        {"selector": "form[action='/login-token'] input[name='token']", "state": "visible"},
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
                {"type": "expect_url_contains", "value": "/login-page"},
                {"type": "expect_title_contains", "value": "AutoPAR"},
                {
                    "type": "wait_for_selector",
                    "selector": "form[action='/login-token'] input[name='token']",
                    "state": "visible",
                },
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
