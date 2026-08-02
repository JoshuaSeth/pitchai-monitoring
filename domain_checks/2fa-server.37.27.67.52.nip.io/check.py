CHECK = {
    "domain": "2fa-server.37.27.67.52.nip.io",
    "url": "https://2fa-server.37.27.67.52.nip.io/healthz",
    "allowed_status_codes": [200],
    "required_text_all": ["ok", "time_utc"],
    "api_contract_checks": [
        {
            "name": "health",
            "method": "GET",
            "path": "/healthz",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["ok", "time_utc"],
            "json_paths_equal": {"ok": True},
            "max_elapsed_ms": 1500,
        },
        {
            "name": "event_bus_outbox_readiness",
            "method": "GET",
            "path": "/readyz",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["ok", "time_utc"],
            "json_paths_equal": {"ok": True},
            "max_elapsed_ms": 1500,
        },
    ],
    "forbidden_text_any": [
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ],
}
