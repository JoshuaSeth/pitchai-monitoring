CHECK = {
    "domain": "skybuyfly.pitchai.net",
    "url": "https://skybuyfly.pitchai.net",
    "expected_title_contains": "SkyBuyFly",
    "capture_headers": [
        "x-aipc-upstream",
        "x-aipc-upstream-status",
    ],
    "proxy": {
        "upstream_header": "x-aipc-upstream",
        "primary_upstreams": ["127.0.0.1:3120"],
        "backup_upstreams": ["127.0.0.1:3121"],
        "alert_on_backup": True,
        "alert_on_unknown": True,
        "alert_on_missing": False,
    },
    "required_selectors_all": [
        {"selector": "meta[property=\"og:title\"]", "state": "attached"},
    ],
    "required_text_all": [
        "SkyBuyFly",
    ],
    "api_contract_checks": [
        {
            "name": "api_health",
            "method": "GET",
            "path": "/api/health",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["status", "service", "timestamp"],
            "json_paths_equal": {"status": "healthy"},
            "max_elapsed_ms": 1500,
        }
    ],
    "synthetic_transactions": [
        {
            "name": "landing_render",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "meta[property=\"og:title\"]", "state": "attached"},
                {"type": "expect_text", "text": "SkyBuyFly"},
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
