CHECK = {
    "domain": "afasask.gzb.nl",
    "url": "https://afasask.gzb.nl",
    # This domain is currently allowed to be in maintenance mode (or even show
    # an upstream 502 page) without triggering alerts.
    "allowed_status_codes": [200, 502, 503],
    "required_selectors_any": [
        {"selector": "text=/maintenance|temporarily unavailable|we'?ll be back/i", "state": "visible"},
        {"selector": "text=/bad gateway|service unavailable|gateway timeout/i", "state": "visible"},
        {"selector": "#token", "state": "visible"},
        {"selector": "#chat-input", "state": "visible"},
        {"selector": "text=Login with Token", "state": "attached"},
    ],
    # Allow maintenance text for this domain.
    "forbidden_text_any": [],
}
