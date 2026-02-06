CHECK = {
    "domain": "dpb.pitchai.net",
    "url": "https://dpb.pitchai.net",
    "expected_title_contains": "Deplanbook",
    "expected_final_host_suffix": "deplanbook.com",
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
        }
    ],
    "synthetic_transactions": [
        {
            "name": "open_diary_page",
            "steps": [
                {"type": "goto"},
                {"type": "click", "selector": "a[href=\"/diary\"]"},
                {"type": "expect_url_contains", "value": "/diary"},
            ],
        }
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "not found",
    ],
}
