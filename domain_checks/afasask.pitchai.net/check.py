CHECK = {
    "domain": "afasask.pitchai.net",
    "url": "https://afasask.pitchai.net",
    "expected_title_contains": "AFASAsk",
    "required_selectors_all": [
        {"selector": "nav", "state": "visible"},
    ],
    "required_text_all": [
        "AFASAsk",
    ],
    "synthetic_transactions": [
        {
            "name": "landing_render",
            "steps": [
                {"type": "goto"},
                {"type": "wait_for_selector", "selector": "nav", "state": "visible"},
                {"type": "expect_text", "text": "AFASAsk"},
            ],
        }
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ],
}
