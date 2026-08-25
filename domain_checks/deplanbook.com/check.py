CHECK = {
    "domain": "deplanbook.com",
    "url": "https://deplanbook.com",
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
    "api_contract": {"interval_minutes": 1, "down_after_failures": 1},
    "api_contract_checks": [
        {
            "name": "database_readiness",
            "service": "deplanbook-play",
            "method": "GET",
            "path": "/readyz",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": [
                "status",
                "service",
                "commit",
                "rotation.phase",
                "rotation.database_identity_sha256",
                "checks.process_identity",
                "checks.database_transaction",
                "checks.database_identity",
                "checks.migration_head",
                "checks.reference_data",
            ],
            "json_paths_equal": {
                "status": "ready",
                "service": "deplanbook-play",
                "checks.process_identity": "ok",
                "checks.database_transaction": "ok",
                "checks.database_identity": "ok",
                "checks.migration_head": "ok",
                "checks.reference_data": "ok",
            },
            "failure_class_json_path": "failure_class",
            "application_commit_json_path": "commit",
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
