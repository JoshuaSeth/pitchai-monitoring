CHECK = {
    "domain": "afasask.gzb.nl",
    "url": "https://afasask.gzb.nl/chat_mini/gzb/start?floating=false&reload=true&mode=codex&intensity=medium",
    "http_timeout_seconds": 30.0,
    "browser_timeout_seconds": 60.0,
    "expected_title_contains": "GZB - Chat",
    "required_selectors_all": [
        {"selector": "#chat-input", "state": "visible"},
        {"selector": ".chat-submit", "state": "visible"},
        {"selector": "text=/AFASASK/i", "state": "visible"},
        {"selector": "text=/Medium/i", "state": "visible"},
    ],
    "synthetic_transactions": [
        {
            "name": "codex_medium_shell_ready",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "#chat-input", "state": "visible"},
                {"type": "wait_for_selector", "selector": ".chat-submit", "state": "visible"},
            ],
        }
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "Mislukt",
    ],
}
