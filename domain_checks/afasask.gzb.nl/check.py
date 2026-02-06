CHECK = {
    "domain": "afasask.gzb.nl",
    "url": "https://afasask.gzb.nl",
    # This endpoint sometimes responds slowly; use higher timeouts to reduce false alerts.
    "http_timeout_seconds": 30.0,
    "browser_timeout_seconds": 60.0,
    # This domain is currently allowed to be in maintenance mode (or even show
    # an upstream 502 page) without triggering alerts.
    "allowed_status_codes": [200, 502, 503],
    "required_selectors_any": [
        {"selector": "text=/afas online/i", "state": "visible"},
        {"selector": "text=/maintenance|temporarily unavailable|we'?ll be back/i", "state": "visible"},
        {"selector": "text=/bad gateway|service unavailable|gateway timeout/i", "state": "visible"},
        {"selector": "#token", "state": "visible"},
        {"selector": "#chat-input", "state": "visible"},
        {"selector": "text=Login with Token", "state": "attached"},
    ],
    "synthetic_transactions": [
        {
            "name": "landing_or_maintenance",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "body", "state": "visible"},
            ],
        }
    ],
    # Allow maintenance text for this domain.
    "forbidden_text_any": [],
}
