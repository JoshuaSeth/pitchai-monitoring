CHECK = {
    "domain": "quickchat.pitchai.net",
    "url": "https://quickchat.pitchai.net",
    "expected_title_contains": "PitchAI Chat",
    "required_selectors_all": [
        {"selector": "#main", "state": "visible"},
    ],
    "required_text_all": [
        "PitchAI Chat",
    ],
    "synthetic_transactions": [
        {
            "name": "landing_render",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "#main", "state": "visible"},
                {"type": "expect_text", "text": "PitchAI Chat"},
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
