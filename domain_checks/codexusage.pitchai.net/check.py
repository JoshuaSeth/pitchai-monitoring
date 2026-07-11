CHECK = {
    "domain": "codexusage.pitchai.net",
    "url": "https://codexusage.pitchai.net/healthz",
    "expected_final_host_suffix": "codexusage.pitchai.net",
    "required_selectors_all": [
        {"selector": "body", "state": "visible"},
    ],
    "required_text_all": [
        "status",
        "ok",
        "source_stale",
    ],
    "api_contract_checks": [
        {
            "name": "redacted_health",
            "method": "GET",
            "url": "https://codexusage.pitchai.net/healthz",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["status", "generated_at", "source_stale"],
            "json_paths_equal": {"status": "ok", "source_stale": False},
            "max_elapsed_ms": 1500,
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
