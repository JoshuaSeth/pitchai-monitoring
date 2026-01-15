CHECK = {
    "domain": "afasask.gzb.nl",
    "url": "https://afasask.gzb.nl",
    # This domain is treated as "up" if we can reach the app UI.
    # We accept either the token login UI OR the chat UI itself.
    "required_selectors_any": [
        {"selector": "#token", "state": "visible"},
        {"selector": "#chat-input", "state": "visible"},
        {"selector": "text=Login with Token", "state": "attached"},
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ],
}
