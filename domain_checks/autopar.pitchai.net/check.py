CHECK = {
    "domain": "autopar.pitchai.net",
    "url": "https://autopar.pitchai.net",
    "expected_title_contains": "AutoPAR Web App",
    "required_selectors_all": [
        {"selector": "script#wss-connection", "state": "attached"},
        {"selector": "input[name=token], #token", "state": "visible"},
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ],
}
